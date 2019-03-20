//! A generic log proxy implementation.
//!
//! This module defines the [`LogProxy`] struct and implements the [`Log`]
//! trait for it.
//!
//! # Use
//!
//! # Example
//!
//! [`LogProxy`]: ./struct.LogProxy.html
//! [`Log`]: ../trait.Log.html

use crate::log::{Log, Loglevel, LoglevelFilter, Record, Sender};

/// A [`LogProxy`] is a logger implementation (`Log`) which sends log records
/// using its Sender side of a Channel.
///
/// [`LogProxy`]: ./struct.LogProxy.html
#[derive(Debug)]
pub struct LogProxy<T: Sender> {
    name: String,
    level: LoglevelFilter,
    sender: T,
}

impl<T: Sender<Item = Record>> LogProxy<T> {
    fn new(name: impl Into<String>, level: LoglevelFilter, sender: T) -> LogProxy<T> {
        LogProxy {
            name: name.into(),
            level,
            sender,
        }
    }

    /// Return a new boxed LogProxy for the provided sender and level.
    pub fn boxed(name: impl Into<String>, level: LoglevelFilter, sender: T) -> Box<LogProxy<T>> {
        Box::new(LogProxy::new(name, level, sender))
    }
}

impl<T: Sender<Item = Record>> Log for LogProxy<T> {
    fn name(&self) -> &str {
        self.name.as_ref()
    }
    fn enabled(&self, level: Loglevel) -> bool {
        self.level <= LoglevelFilter::from(level)
    }
    fn log(&self, record: Record) {
        self.sender
            .send(record)
            .expect("LogProxy failed to send record");
    }
}
