#include <dqcsim_raw.hpp>
#include "gtest/gtest.h"

// Sanity check the handle API.
TEST(handle, sanity) {
  // Create handle.
  dqcs_handle_t a = dqcs_cmd_new("a", "b");
  ASSERT_NE(a, 0) << "Unexpected error: " << dqcs_explain();

  // Check that the handle is OK.
  EXPECT_EQ(dqcs_handle_type(a), dqcs_handle_type_t::DQCS_HTYPE_ARB_CMD);
  EXPECT_STREQ(dqcs_handle_dump(a), "ArbCmd(\n    ArbCmd {\n        interface_identifier: \"a\",\n        operation_identifier: \"b\",\n        data: ArbData {\n            json: Object(\n                {}\n            ),\n            args: []\n        }\n    }\n)");

  // Delete handle.
  EXPECT_EQ(dqcs_handle_delete(a), dqcs_return_t::DQCS_SUCCESS);

  // Check that the handle is no longer OK.
  EXPECT_EQ(dqcs_handle_type(a), dqcs_handle_type_t::DQCS_HTYPE_INVALID);
  EXPECT_STREQ(dqcs_handle_dump(a), nullptr);
  EXPECT_EQ(dqcs_explain(), "Invalid argument: handle " + std::to_string(a) + " is invalid");
}

// Test that only commands with valid characters can be constructed.
TEST(cmd, construction) {
  dqcs_handle_t a;
  EXPECT_NE(a = dqcs_cmd_new("a", "b"), 0) << "Unexpected error: " << dqcs_explain();
  EXPECT_EQ(dqcs_handle_delete(a), dqcs_return_t::DQCS_SUCCESS);

  EXPECT_NE(a = dqcs_cmd_new("foo", "BAR23"), 0) << "Unexpected error: " << dqcs_explain();
  EXPECT_EQ(dqcs_handle_delete(a), dqcs_return_t::DQCS_SUCCESS);

  EXPECT_EQ(a = dqcs_cmd_new("nope", ""), 0);
  EXPECT_STREQ(dqcs_explain(), "Invalid argument: identifiers must not be empty");
  EXPECT_EQ(dqcs_handle_delete(a), dqcs_return_t::DQCS_FAILURE);

  EXPECT_EQ(a = dqcs_cmd_new("???", "also_nope"), 0);
  EXPECT_STREQ(dqcs_explain(), "Invalid argument: \"???\" is not a valid identifier; it contains characters outside [a-zA-Z0-9_]");
  EXPECT_EQ(dqcs_handle_delete(a), dqcs_return_t::DQCS_FAILURE);

  EXPECT_EQ(a = dqcs_cmd_new(nullptr, "no"), 0);
  EXPECT_STREQ(dqcs_explain(), "Invalid argument: unexpected NULL string");
  EXPECT_EQ(dqcs_handle_delete(a), dqcs_return_t::DQCS_FAILURE);

  EXPECT_EQ(a = dqcs_cmd_new("NO", nullptr), 0);
  EXPECT_STREQ(dqcs_explain(), "Invalid argument: unexpected NULL string");
  EXPECT_EQ(dqcs_handle_delete(a), dqcs_return_t::DQCS_FAILURE);
}

// Test identifier getters and checkers.
TEST(cmd, getters) {
  dqcs_handle_t a;
  EXPECT_NE(a = dqcs_cmd_new("foo", "bar"), 0) << "Unexpected error: " << dqcs_explain();

  const char *s;
  EXPECT_STREQ(s = dqcs_cmd_iface_get(a), "foo") << "Unexpected error: " << dqcs_explain();
  if (s) free((void*)s);
  EXPECT_STREQ(s = dqcs_cmd_oper_get(a), "bar") << "Unexpected error: " << dqcs_explain();
  if (s) free((void*)s);

  EXPECT_EQ(dqcs_cmd_iface_cmp(a, "foo"), dqcs_bool_return_t::DQCS_TRUE);
  EXPECT_EQ(dqcs_cmd_iface_cmp(a, "fOo"), dqcs_bool_return_t::DQCS_FALSE);
  EXPECT_EQ(dqcs_cmd_iface_cmp(a, ""), dqcs_bool_return_t::DQCS_FALSE);
  EXPECT_EQ(dqcs_cmd_iface_cmp(a, nullptr), dqcs_bool_return_t::DQCS_BOOL_FAILURE);
  EXPECT_STREQ(dqcs_explain(), "Invalid argument: unexpected NULL string");

  EXPECT_EQ(dqcs_cmd_oper_cmp(a, "bar"), dqcs_bool_return_t::DQCS_TRUE);
  EXPECT_EQ(dqcs_cmd_oper_cmp(a, "BAR"), dqcs_bool_return_t::DQCS_FALSE);
  EXPECT_EQ(dqcs_cmd_oper_cmp(a, "rt87erft"), dqcs_bool_return_t::DQCS_FALSE);
  EXPECT_EQ(dqcs_cmd_oper_cmp(a, nullptr), dqcs_bool_return_t::DQCS_BOOL_FAILURE);
  EXPECT_STREQ(dqcs_explain(), "Invalid argument: unexpected NULL string");

  EXPECT_EQ(dqcs_handle_delete(a), dqcs_return_t::DQCS_SUCCESS);
}

// Test some arb API calls. All of them should work on cmds as well.
TEST(cmd, arb) {
  dqcs_handle_t a, c;
  EXPECT_NE(c = dqcs_cmd_new("foo", "bar"), 0) << "Unexpected error: " << dqcs_explain();

  EXPECT_EQ(dqcs_arb_json_set_str(c, "{\"answer\": 42}"), dqcs_return_t::DQCS_SUCCESS) << "Unexpected error: " << dqcs_explain();
  EXPECT_EQ(dqcs_arb_push_str(c, "a"), dqcs_return_t::DQCS_SUCCESS) << "Unexpected error: " << dqcs_explain();
  EXPECT_EQ(dqcs_arb_push_str(c, "b"), dqcs_return_t::DQCS_SUCCESS) << "Unexpected error: " << dqcs_explain();
  EXPECT_EQ(dqcs_arb_push_str(c, "c"), dqcs_return_t::DQCS_SUCCESS) << "Unexpected error: " << dqcs_explain();

  EXPECT_NE(a = dqcs_arb_new(), 0) << "Unexpected error: " << dqcs_explain();
  EXPECT_EQ(dqcs_arb_assign(a, c), dqcs_return_t::DQCS_SUCCESS) << "Unexpected error: " << dqcs_explain();
  EXPECT_EQ(dqcs_handle_delete(c), dqcs_return_t::DQCS_SUCCESS);

  EXPECT_NE(c = dqcs_cmd_new("baz", "quux"), 0) << "Unexpected error: " << dqcs_explain();
  EXPECT_EQ(dqcs_arb_assign(c, a), dqcs_return_t::DQCS_SUCCESS) << "Unexpected error: " << dqcs_explain();
  EXPECT_EQ(dqcs_handle_delete(a), dqcs_return_t::DQCS_SUCCESS);

  EXPECT_EQ(dqcs_arb_len(c), 3);

  const char *s;
  EXPECT_STREQ(s = dqcs_arb_json_get_str(c), "{\"answer\":42}");
  if (s) free((void*)s);
  EXPECT_STREQ(s = dqcs_arb_pop_str(c), "c");
  if (s) free((void*)s);
  EXPECT_STREQ(s = dqcs_arb_pop_str(c), "b");
  if (s) free((void*)s);
  EXPECT_STREQ(s = dqcs_arb_pop_str(c), "a");
  if (s) free((void*)s);

  EXPECT_EQ(dqcs_handle_delete(c), dqcs_return_t::DQCS_SUCCESS);
}
