"""Contains the base classes for configuring and running simulations."""

import dqcsim._dqcsim as raw
from dqcsim.common import *
from dqcsim.plugin import *
import sys
import os
import zlib

class Simulator(object):
    """Represents a DQCsim simulator managed by Python.

    The constructor (`__init__()`), `with_frontend()`, `with_operator()`, and
    `with_backend()` may be used to configure the simulation. After that, it
    may be started with `simulate()` and stopped with `stop()` as many times as
    desired.

    Between invocations of `simulate()` and `stop()`, the calling Python script
    functions as the host process. It can call `start()`, `wait()`, `send()`,
    `recv()`, `yeeld()`, and `arb()` to communicate with the simulated quantum
    accelerator formed by the plugins.

    For simple simulations, `run()` may also be used for convenience. It
    combines `simulate()`, `start()`, `wait()`, and `stop()`.
    """

    def __init__(self, *args, **kwargs):
        """Constructs a simulation configuration.

        Each positional argument represents a plugin that the constructor will
        add for you, ordered from frontend to backend. You may also not specify
        any positional arguments if you would rather add them later using
        `with_frontend()`, `with_operator()`, and/or `with_backend()`. You can
        specify the plugins using the following types of values:

          - `str`: constructs the plugin in the same way that the command-line
            interface does it.
          - `(str, None)`: specifies the path to the plugin executable
            directly.
          - `(str, str)`: specifies the path to the plugin executable and the
            script it must run directly.
          - `Frontend`/`Operator`/`Backend`: constructs a DQCsim-managed thread
            that runs the given plugin definition instead of launching an
            external process for it.
          - `(str) -> None`: the specified callback is used to spawn the
            plugin.
          - `(<any of the above>, {key: value})`: the last entry of the tuple,
            which must be a dictionary, is used to configure the plugin (it is
            sent to `**kwargs` when the plugin is added).

        For more information, refer to `with_frontend()`.

        Besides the positional arguments, you can provide a number of keyword
        arguments to configure the behavior of the simulator:

          - `repro = "keep", "absolute", "relative", or None` (default: `"keep"`)

            Configures whether logging for the purpose of generating a
            reproduction file is enabled, and if it is, what style to use for
            storing filesystem paths.

          - `dqcsim_verbosity = Loglevel` (default: `Loglevel.TRACE`)

            Sets the minimum loglevel that a message generated by DQCsim itself
            must have for it to be logged anywhere, analogous to the
            plugin-specific verbosities. This defaults to `Loglevel.TRACE` to
            effectively disable the filter.

          - `stderr_verbosity = Loglevel` (default: `Loglevel.INFO`)

            Sets the minimum loglevel needed for a message to be logged to
            `stderr`.

          - `log_capture = callback, str, or None` (default: `None`)

            Specifies an alternative destination for log messages. If a
            callback is specified, it is called for every log message passing
            all the filters. If a string is specified, the messages are
            forwarded to Python's `logging` module using the specified string
            for the logger name. Note that this adds DQCsim's trace and note
            loglevels to `logging` using severities 5 and 25 respectively. If
            `None` is specified, forwarding is disabled.

            The user-defined callback is called with the following positional
            arguments:

              - `str`: the log message, without any metadata added to it.
              - `str`: the name of the logger that produced the message.
              - `Loglevel`: the loglevel assigned to the message.
              - `str`: string describing the logical source of the log message.
                Its significance depends on the programming language of the
                plugin that produced it. It is set to the Rust crate/module
                path for Rust programs, the Python module for Python scripts,
                and is left blank for C(++) programs.
              - `str`: string specifying the filename of the source that
                produced the message (`*.rs`, `*.cpp`, `*.py`, etc.)
              - `int`: the line number within the aforementioned source.
              - `int`: message timestamp, in nanoseconds since the Unix epoch.
              - `int`: process ID of the generating process.
              - `int`: thread ID of the generating thread.

          - `log_capture_verbosity = Loglevel` (default: `Loglevel.TRACE`)

            Sets the minimum loglevel needed for a message to be sent to the
            sink specified by `log_capture` (if any). This defaults to
            `Loglevel.TRACE` to effectively disable the filter.

          - `tee = {str: Loglevel}` (default: `{}`)

            Each entry in the dictionary consists of a log output filename as
            key and a loglevel filter as the value. It causes log messages
            generated by this plugin (though not including any captured
            streams) that pass the specified filter to be logged to the given
            log file, in addition to their normal handling.
        """
        super().__init__()
        self._sim_handle = None
        self._front = None
        self._opers = []
        self._back = None

        # Check the keyword arguments.
        self._repro = kwargs.pop('repro', 'keep')
        if self._repro not in {'keep', 'absolute', 'relative', None}:
            raise TypeError("repro must be 'keep', 'absolute', 'relative', or None")

        self._dqcsim_verbosity = kwargs.pop('dqcsim_verbosity', Loglevel.TRACE)
        if not isinstance(self._dqcsim_verbosity, Loglevel):
            raise TypeError("dqcsim_verbosity must be a Loglevel")

        self._stderr_verbosity = kwargs.pop('stderr_verbosity', Loglevel.INFO)
        if not isinstance(self._stderr_verbosity, Loglevel):
            raise TypeError("stderr_verbosity must be a Loglevel")

        self._log_capture = kwargs.pop('log_capture', None)
        if self._log_capture is not None:
            if isinstance(self._log_capture, str):
                import logging
                logging.addLevelName(25, "NOTE")
                logging.addLevelName(5, "TRACE")
                logger = logging.getLogger(self._log_capture)
                def to_logging(message, name, level, source, filename, lineno, nanotime, tid, pid):
                    if level == Loglevel.TRACE:
                        level = 5
                    elif level == Loglevel.DEBUG:
                        level = logging.DEBUG
                    elif level == Loglevel.INFO:
                        level = logging.INFO
                    elif level == Loglevel.NOTE:
                        level = 25
                    elif level == Loglevel.WARN:
                        level = logging.WARNING
                    elif level == Loglevel.ERROR:
                        level = logging.ERROR
                    elif level == Loglevel.FATAL:
                        level = logging.CRITICAL
                    else:
                        level = logging.NOTSET
                    rec = logger.makeRecord(name, level, filename, lineno, message, (), None, source)
                    logger.handle(rec)
                self._log_capture = to_logging
            elif not callable(self._log_capture):
                raise TypeError("log_capture must be callable or a string identifying a logger from the logging library")
            cb = self._log_capture
            def transmute(message, name, level, source, filename, lineno, time_s, time_ns, tid, pid):
                cb(message, name, Loglevel(level), source, filename, lineno, time_s * 1000000000 + time_ns, tid, pid)
            # Handle trace functions.
            trace_fn = sys.gettrace()
            if trace_fn is None:
                self._log_capture = transmute # no_kcoverage
            else:
                # We have a trace function, probably set by kcov for getting
                # coverage data. Callbacks from the C API run from a new
                # context every time, so we need to set the trace function
                # before calling into the callback.
                def traced(*args):
                    sys.settrace(trace_fn) # no_kcoverage
                    transmute(*args) # no_kcoverage
                self._log_capture = traced

        self._log_capture_verbosity = kwargs.pop('log_capture_verbosity', Loglevel.TRACE)
        if not isinstance(self._log_capture_verbosity, Loglevel):
            raise TypeError("log_capture_verbosity must be a Loglevel")

        self._tee = dict(kwargs.pop('tee', {}))
        for key, value in self._tee.items():
            if not isinstance(key, str):
                raise TypeError("tee file key must be a string")
            if not isinstance(value, Loglevel):
                raise TypeError("tee file value must be a Loglevel")

        if kwargs:
            raise TypeError("unexpected keyword argument {!r}".format(next(iter(kwargs.keys()))))

        # Add the plugins.
        if args:
            def add(fn, args):
                if not isinstance(args, tuple):
                    args = [args]
                else:
                    args = list(args)
                if args and isinstance(args[-1], dict):
                    kwargs = args[-1]
                    del args[-1]
                else:
                    kwargs = {}
                return fn(*args, **kwargs)

            add(self.with_frontend, args[0])
            if len(args) >= 2:
                add(self.with_backend, args[-1])
                for arg in args[1:-1]:
                    add(self.with_operator, arg)

    def _plugin_factory(self, plugin_type, *args, **kwargs):
        """Makes a function that constructs an "`xcfg`" handle for the
        specified plugin.

        `plugin_type` must be set to the expected plugin type code, taken from
        `raw.DQCS_PTYPE_*`. `*args` and `**kwargs` follow the formats described
        in the docs for `Simulator.with_frontend()`. These should be
        typechecked as much as possible during construction of the function vs.
        execution.
        """
        if self._sim_handle is not None:
            raise RuntimeError("Cannot reconfigure simulation while it is running")

        # Check plugin type argument.
        if plugin_type not in {raw.DQCS_PTYPE_FRONT, raw.DQCS_PTYPE_OPER, raw.DQCS_PTYPE_BACK}:
            raise TypeError("plugin_type is not set to a valid plugin type code")

        # Check *args.
        arg_mode = None
        if len(args) == 1:
            if isinstance(args[0], str):
                arg_mode = 1
                specification = str(args[0])
            elif isinstance(args[0], Frontend) and plugin_type == raw.DQCS_PTYPE_FRONT:
                arg_mode = 3
                definition = args[0]
            elif isinstance(args[0], Operator) and plugin_type == raw.DQCS_PTYPE_OPER:
                arg_mode = 3
                definition = args[0]
            elif isinstance(args[0], Backend) and plugin_type == raw.DQCS_PTYPE_BACK:
                arg_mode = 3
                definition = args[0]
            elif callable(args[0]):
                arg_mode = 4
                callback = args[0]
        elif len(args) == 2 and isinstance(args[0], str) and (args[1] is None or isinstance(args[1], str)):
            arg_mode = 2
            executable = os.path.realpath(args[0])
            script = os.path.realpath(args[1])
        if arg_mode is None:
            raise TypeError("invalid combination of positional arguments")

        # Check **kwargs.
        name = kwargs.pop('name', None)
        if name is None:
            name = ""
        else:
            name = str(name)

        init = kwargs.pop('init', [])
        if isinstance(init, ArbCmd):
            init = [init]
        init = list(init)
        for cmd in init:
            if not isinstance(cmd, ArbCmd):
                raise TypeError("init must be a single ArbCmd or a list/tuple of ArbCmds")

        verbosity = kwargs.pop('verbosity', Loglevel.TRACE)
        if not isinstance(verbosity, Loglevel):
            raise TypeError("verbosity must be a Loglevel")

        tee = dict(kwargs.pop('tee', {}))
        for key, value in tee.items():
            if not isinstance(key, str):
                raise TypeError("tee file key must be a string")
            if not isinstance(value, Loglevel):
                raise TypeError("tee file value must be a Loglevel")

        if arg_mode == 1 or arg_mode == 2:
            # Pop kwargs that are only available for processes.
            env = dict(kwargs.pop('env', {}))
            for key, value in env.items():
                if not isinstance(key, str):
                    raise TypeError("environment variable key must be a string")
                if value is not None and not isinstance(value, str):
                    raise TypeError("environment variable value must be a string or None")

            work = kwargs.pop('work', None)
            if work is not None:
                work = str(work)

            stderr = kwargs.pop('stderr', Loglevel.INFO)
            if stderr is not None and not isinstance(stderr, Loglevel):
                raise TypeError("stderr must be a Loglevel or None")

            stdout = kwargs.pop('stdout', Loglevel.INFO)
            if stdout is not None and not isinstance(stdout, Loglevel):
                raise TypeError("stdout must be a Loglevel or None")

            accept_timeout = float(kwargs.pop('accept_timeout', 5.0))
            shutdown_timeout = float(kwargs.pop('shutdown_timeout', 5.0))

        if kwargs:
            raise TypeError("unexpected keyword argument {!r}".format(next(iter(kwargs.keys()))))

        # Produce the constructor function.
        if arg_mode == 1 or arg_mode == 2:
            # Plugin process; pcfg interface.
            def fn():
                # Construct handle.
                if arg_mode == 1:
                    pcfg = Handle(raw.dqcs_pcfg_new(plugin_type, name, specification))
                elif arg_mode == 2:
                    pcfg = Handle(raw.dqcs_pcfg_new_raw(plugin_type, name, executable, script))

                # Apply configuration.
                with pcfg as p:
                    # Init commands.
                    for cmd in init:
                        cmd = cmd._to_raw()
                        with cmd as c:
                            raw.dqcs_pcfg_init_cmd(p, c)

                    # Logging.
                    raw.dqcs_pcfg_verbosity_set(p, int(verbosity))
                    for key, value in tee.items():
                        raw.dqcs_pcfg_tee(p, int(value), key)

                    # Process environment.
                    if work is not None:
                        raw.dqcs_pcfg_work_set(p, work)
                    for key, value in env.items():
                        if value is None:
                            raw.dqcs_pcfg_env_unset(p, key)
                        else:
                            raw.dqcs_pcfg_env_set(p, key, value)

                    # Stream capture.
                    if stderr is None:
                        raw.dqcs_pcfg_stderr_mode_set(p, raw.DQCS_LOG_PASS)
                    else:
                        raw.dqcs_pcfg_stderr_mode_set(p, int(stderr))
                    if stdout is None:
                        raw.dqcs_pcfg_stdout_mode_set(p, raw.DQCS_LOG_PASS)
                    else:
                        raw.dqcs_pcfg_stdout_mode_set(p, int(stdout))

                    # Timeouts.
                    raw.dqcs_pcfg_accept_timeout_set(p, accept_timeout)
                    raw.dqcs_pcfg_shutdown_timeout_set(p, shutdown_timeout)

                # Return the handle.
                return pcfg

        elif arg_mode == 3 or arg_mode == 4:
            # Plugin thread; tcfg interface.
            def fn():
                # Construct handle.
                if arg_mode == 3:
                    with definition._to_pdef() as pd:
                        tcfg = Handle(raw.dqcs_tcfg_new(pd, name))
                elif arg_mode == 4:
                    tcfg = Handle(raw.dqcs_tcfg_new_raw_pyfun(plugin_type, name, callback))

                # Apply configuration.
                with tcfg as t:
                    # Init commands.
                    for cmd in init:
                        cmd = cmd._to_raw()
                        with cmd as c:
                            raw.dqcs_tcfg_init_cmd(t, c)

                    # Logging.
                    raw.dqcs_tcfg_verbosity_set(t, int(verbosity))
                    for key, value in tee.items():
                        raw.dqcs_tcfg_tee(t, int(value), key)

                # Return the handle.
                return tcfg

        return fn

    def with_frontend(self, *args, **kwargs):
        """Sets the frontend plugin for the simulation.

        This must be called prior to launching the simulation, either by the
        constructor or by you manually. If it is called multiple times, the
        last call counts. The function mutates and returns `self`, so it can be
        used for both builder-style constructions or mutation-based
        construction.

        There are five supported combinations of positional arguments,
        representing five different ways to launch a plugin:

          - `str`

            Constructs a plugin in the same way that the command-line interface
            does it. That is, a single string conforming to any of the
            following:

              - a valid path to the plugin executable;
              - the basename of the plugin executable with implicit `dqcsfe`
                prefix, searched for in the current working directory and in
                the system `$PATH`;
              - a valid path to a script file with a file extension. In this
                case, the above rule is run for a plugin named by the file
                extension of the script file. For instance, if `test.py` is
                specified, the library will look for an executable named
                `dqcsfepy`. The script filename is passed to the plugin through
                its sole command-line argument.

          - `str, None`

            Constructs a plugin using the given direct path to the native
            plugin executable. The path can be absolute or relative to the
            current working directory, but other than that no desugaring is
            performed.

          - `str, str`

            As above, but for non-native plugins. The first string must be the
            path to the interpreter used to run the non-native plugin, the
            second must be the path to the plugin script. Both paths can either
            be absolute or relative to the current working directory.

          - `Frontend`

            Instead of launching a process for the frontend plugin, it is
            launched in a thread within the context of this Python interpreter.
            The dqcsim library will take care of this launch.

          - `(str) -> None`

            Instead of launching a process for the frontend plugin, it is
            launched in a thread within the context of this Python interpreter.
            You are in charge of doing this through a function that you
            provide. This function takes the simulator address string as its
            sole argument, and in some way pass it to `Frontend.start()` or
            `Frontend.run()`. The function's return value (if any) is ignored.

        Besides the positional arguments, you can provide a number of keyword
        arguments to configure the behavior of the plugin:

          - `name = str` (default: `"front"`)

            Sets the name of the plugin, used to refer to it in log messages or
            in a reproduction file.

          - `init = ArbCmd or [ArbCmd]` (default: `[]`)

            Specifies a single `ArbCmd` or a list of `ArbCmd`s to send to the
            plugin's initialization callback.

          - `env = {str: str or None}` (default: `{}`)

            Configures the environment variables passed to the plugin process.
            The set of variables is based on the current environment, then
            modified using the given dictionary. Specifying a variable name as
            key and a string value sets or overrides the environment variable.
            Setting the value to `None` removes it from the environment. This
            is only supported for plugin processes.

          - `work = str or None` (default: `None`)

            If a string is specified, the plugin process will launch using the
            given string as its working directory. `None` causes the current
            working directory to be used. This is only supported for plugin
            processes.

          - `verbosity = Loglevel` (default: `Loglevel.TRACE`)

            Sets the minimum loglevel a log message must have for it to be
            forwarded to the simulator process. This defaults to
            `Loglevel.TRACE` to effectively disable the filter.

          - `tee = {str: Loglevel}` (default: `{}`)

            Each entry in the dictionary consists of a log output filename as
            key and a loglevel filter as the value. It causes log messages
            generated by this plugin (though not including any captured
            streams) that pass the specified filter to be logged to the given
            log file, in addition to their normal handling.

          - `stderr = Loglevel or None` (default: `Loglevel.INFO`)

            Configures if/how the `stderr` stream of the plugin process is
            captured. If `Loglevel.OFF` is specified, the `stderr` stream is
            ignored. Any other loglevel causes each line of output to be logged
            using a message of the specified level. Passing `None` prevents the
            stderr stream from being captured at all, so the messages will
            appear in this Python process' `stderr` stream. This is only
            supported for plugin processes, since threads do not have separate
            streams.

          - `stdout = Loglevel or None` (default: `Loglevel.INFO`)

            Same as `stderr`, but for the `stdout` stream.

          - `accept_timeout = float (default: `5.0` seconds)

            Sets the amount of time that DQCsim will wait in seconds for the
            plugin to finish starting up and connect to the simulator process.
            This is currently only supported for plugin processes.

          - `shutdown_timeout = float (default: `5.0` seconds)

            Sets the amount of time that DQCsim will wait in seconds for the
            plugin to shut down after the simulator sends the abort request to
            it. This is currently only supported for plugin processes.
        """
        self._front = self._plugin_factory(raw.DQCS_PTYPE_FRONT, *args, **kwargs)
        return self

    def with_operator(self, *args, **kwargs):
        """Adds an operator plugin to the simulation.

        Operators must be added in front to back order by calling this function
        for every operator. The function mutates and returns `self`, so it can
        be used for both builder-style constructions or mutation-based
        construction.

        Operators are constructed in the same way as frontends and backends.
        Refer to `with_frontend()` for information about the positional and
        keyword arguments, replacing `Frontend` with `Operator` and `dqcsfe`
        with `dqcsop`. The default name is `"op<N>"`, where `N` is the operator
        index in front-to-back order starting at 1.
        """
        self._opers.append(self._plugin_factory(raw.DQCS_PTYPE_OPER, *args, **kwargs))
        return self

    def with_backend(self, *args, **kwargs):
        """Sets the backend plugin for the simulation.

        If this is not called either manually or by the constructor, the
        simulation defaults to using the QX backend. If it is called multiple
        times, the last call counts. The function mutates and returns `self`,
        so it can be used for both builder-style constructions or
        mutation-based construction.

        Backends are constructed in the same way as frontends and operators.
        Refer to `with_frontend()` for information about the positional and
        keyword arguments, replacing `Frontend` with `Backend` and `dqcsfe`
        with `dqcsbe`. The default name is `"back"`.
        """
        self._back = self._plugin_factory(raw.DQCS_PTYPE_BACK, *args, **kwargs)
        return self

    def run(self, *args, **kwargs):
        """Runs a simple simulation without host-accelerator interaction.

        This is completely equivalent to calling:

            sim.simulate()
            sim.start(*args, **kwargs)
            ret = sim.wait()
            sim.stop()
            return ret

        If a simulation was already running, the `simulate()` and `stop()`
        calls are omitted.
        """
        if self._sim_handle is None:
            self.simulate()
            self.start(*args, **kwargs)
            ret = self.wait()
            self.stop()
        else:
            self.start(*args, **kwargs)
            ret = self.wait()
        return ret

    def simulate(self, seed=None):
        """Starts the simulation.

        `seed` optionally specifies the random seed used for the simulation.
        An `int` argument between `0` and `2^64-1` inclusive specifies the
        seed directly. For other types `zlib.adler32(str(...).encode('utf-8'))`
        is applied to get a number, which is then cast to a 32-bit unsigned
        number. If `None` is specified or the argument is omitted, DQCsim will
        randomize the seed based on the highest resolution timestamp the
        operating system is capable of providing.
        """
        if self._sim_handle is not None:
            raise RuntimeError("Cannot run multiple simulations at once")
        if self._front is None:
            raise RuntimeError("Frontend plugin was never specified")
        if self._back is None:
            self.with_backend("qx")

        # Create a new configuration.
        scfg_ob = Handle(raw.dqcs_scfg_new())
        with scfg_ob as scfg:

            # Configure the seed.
            if seed is not None:
                if isinstance(seed, int) and seed >= 0 and seed <= 0xFFFFFFFFFFFFFFFF:
                    raw.dqcs_scfg_seed_set(scfg, seed)
                else:
                    raw.dqcs_scfg_seed_set(scfg, zlib.adler32(str(seed).encode('utf-8')) & 0xFFFFFFFF)

            # Configure reproduction file logging.
            if self._repro is None:
                raw.dqcs_scfg_repro_disable(scfg)
            else:
                raw.dqcs_scfg_repro_path_style_set(scfg, {
                    'keep': raw.DQCS_PATH_STYLE_KEEP,
                    'relative': raw.DQCS_PATH_STYLE_RELATIVE,
                    'absolute': raw.DQCS_PATH_STYLE_ABSOLUTE,
                }[self._repro])

            # Configure regular logging.
            raw.dqcs_scfg_dqcsim_verbosity_set(scfg, int(self._dqcsim_verbosity))
            raw.dqcs_scfg_stderr_verbosity_set(scfg, int(self._stderr_verbosity))
            if self._log_capture is not None:
                raw.dqcs_scfg_log_callback_pyfun(scfg, int(self._log_capture_verbosity), self._log_capture)
            for key, value in self._tee.items():
                raw.dqcs_scfg_tee(scfg, int(value), key)

            # Push the plugins.
            with self._front() as xcfg:
                raw.dqcs_scfg_push_plugin(scfg, xcfg)
            for oper in self._opers:
                with oper() as xcfg:
                    raw.dqcs_scfg_push_plugin(scfg, xcfg)
            with self._back() as xcfg:
                raw.dqcs_scfg_push_plugin(scfg, xcfg)

            # Start the simulation.
            self._sim_handle = Handle(raw.dqcs_sim_new(scfg))

    def stop(self, repro_out=None):
        """Stops a simulation previously started through `simulate()`.

        `repro_out` can optionally be set to an output filename for a
        reproduction file. If this is omitted or set to `None`, no reproduction
        file is written.
        """
        if self._sim_handle is None:
            raise RuntimeError("No simulation is currently running")

        # Write reproduction file if requested.
        if repro_out is not None:
            with self._sim_handle as sim:
                raw.dqcs_sim_write_reproduction_file(sim, repro_out)

        # Delete the simulation handle.
        raw.dqcs_handle_delete(self._sim_handle.take())
        self._sim_handle = None

    def __enter__(self):
        """Allows you to use a `Simulator` object with the `with` syntax.
        `simulate()` is called at the start of the `with` block; `stop()` is
        called at the end of it."""
        self.simulate()
        return self

    def __exit__(self, *_):
        """Allows you to use a `Simulator` object with the `with` syntax.
        `simulate()` is called at the start of the `with` block; `stop()` is
        called at the end of it."""
        self.stop()

    def start(self, *args, **kwargs):
        """Sends the `start` command to the simulated accelerator.

        Calling this will start execution of the frontend plugin's run callback
        as soon as the host process yields to the simulator. The `ArbData`
        argument passed to it is constructed by passing this function's
        arguments to the constructor of `ArbData` directly.
        """
        if self._sim_handle is None:
            raise RuntimeError("No simulation is currently running")
        with self._sim_handle as sim:
            with ArbData(*args, **kwargs)._to_raw() as data:
                raw.dqcs_sim_start(sim, data)

    def wait(self):
        """Waits for the simulated accelerator to finish executing its run
        callback.

        This function returns an `ArbData` object representing the return value
        of the run callback. If performing this operation would result in a
        deadlock, an exception is thrown instead of waiting indefinitely.
        """
        if self._sim_handle is None:
            raise RuntimeError("No simulation is currently running")
        with self._sim_handle as sim:
            return ArbData._from_raw(Handle(raw.dqcs_sim_wait(sim)))

    def send(self, *args, **kwargs):
        """Sends data to the simulated accelerator.

        This function's arguments are passed directly to the constructor of
        `ArbData` to construct the data object that is to be sent. This object
        can then be retrieved by the frontend's run callback through recv.
        """
        if self._sim_handle is None:
            raise RuntimeError("No simulation is currently running")
        with self._sim_handle as sim:
            with ArbData(*args, **kwargs)._to_raw() as data:
                raw.dqcs_sim_send(sim, data)

    def recv(self):
        """Waits for the simulated accelerator to send data to us.

        This function returns an `ArbData` object representing the data that
        was sent. If performing this operation would result in a deadlock, an
        exception is thrown instead of waiting indefinitely.
        """
        if self._sim_handle is None:
            raise RuntimeError("No simulation is currently running")
        with self._sim_handle as sim:
            return ArbData._from_raw(Handle(raw.dqcs_sim_recv(sim)))

    def yeeld(self):
        """Explicitely sends all queued commands to the accelerator and waits
        for it to block again.

        This is useful if you're waiting for or want to synchronize log
        messages. Note that the function is named yeeld instead of yield
        because yield is a keyword in Python.
        """
        if self._sim_handle is None:
            raise RuntimeError("No simulation is currently running")
        with self._sim_handle as sim:
            raw.dqcs_sim_yield(sim)

    def arb(self, target, *args, **kwargs):
        """Sends an `ArbCmd` to one of the plugins that make up the simulated
        accelerator.

        `target` specifies the plugin that the command is to be sent to. It
        must either be a Pythonic integer index within the front-to-back plugin
        pipeline (that is, 0 for the frontend, 1..x for the operators from
        front to back, -1 for the backend, -2..x for the operators from back to
        front), or a string matching one of the plugin's names.

        The remaining arguments are passed to the constructor for `ArbCmd` to
        generate the command object. This function returns an `ArbData` object
        representing the data that was returned by the command.
        """
        if self._sim_handle is None:
            raise RuntimeError("No simulation is currently running")
        with self._sim_handle as sim:
            with ArbCmd(*args, **kwargs)._to_raw() as cmd:
                if isinstance(target, int):
                    return ArbData._from_raw(Handle(raw.dqcs_sim_arb_idx(sim, int(target), cmd)))
                else:
                    return ArbData._from_raw(Handle(raw.dqcs_sim_arb(sim, str(target), cmd)))

    def get_meta(self, target):
        """Returns metadata information for one of the plugins in the
        pipeline.

        The `target` parameter works the same as the one in `arb()`. The
        returned metadata is a three-tuple of the implementation name, author,
        and version strings. This function only works while a simulation is
        running, since the plugins report their metadata during initialization.
        """
        if self._sim_handle is None:
            raise RuntimeError("No simulation is currently running")
        with self._sim_handle as sim:
            if isinstance(target, int):
                return ( #@
                    raw.dqcs_sim_get_name_idx(sim, int(target)),
                    raw.dqcs_sim_get_author_idx(sim, int(target)),
                    raw.dqcs_sim_get_version_idx(sim, int(target)))
            else:
                return ( #@
                    raw.dqcs_sim_get_name(sim, str(target)),
                    raw.dqcs_sim_get_author(sim, str(target)),
                    raw.dqcs_sim_get_version(sim, str(target)))

    def __len__(self):
        """Returns the number of plugins in the pipeline."""
        l = len(self._opers)
        if self._front is not None:
            l += 1
        if self._back is not None:
            l += 1
        return l

    def __repr__(self):
        return "Simulator()"

    __str__ = __repr__
