import unittest

from simorgh.contracts.validation import ValidationError, check, is_valid, validate


class TestValidator(unittest.TestCase):
    def test_types(self):
        self.assertTrue(is_valid("s", {"type": "string"}))
        self.assertTrue(is_valid(1, {"type": "integer"}))
        self.assertTrue(is_valid(1.0, {"type": "integer"}))  # integral float counts as integer
        self.assertFalse(is_valid(1.5, {"type": "integer"}))
        self.assertTrue(is_valid(1.5, {"type": "number"}))
        self.assertFalse(is_valid(True, {"type": "integer"}))  # bool is not a number
        self.assertFalse(is_valid(True, {"type": "number"}))
        self.assertTrue(is_valid(None, {"type": ["string", "null"]}))
        self.assertFalse(is_valid(None, {"type": "string"}))

    def test_required_and_properties(self):
        schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
        self.assertTrue(is_valid({"a": "x"}, schema))
        self.assertEqual(validate({}, schema), ["$.a: required property missing"])
        self.assertEqual(validate({"a": 1}, schema), ["$.a: expected type string, got int"])

    def test_additional_properties(self):
        closed = {"type": "object", "properties": {}, "additionalProperties": False}
        self.assertFalse(is_valid({"x": 1}, closed))
        typed = {"type": "object", "additionalProperties": {"type": "integer"}}
        self.assertTrue(is_valid({"x": 1}, typed))
        self.assertFalse(is_valid({"x": "s"}, typed))

    def test_enum_const_items(self):
        self.assertFalse(is_valid("c", {"enum": ["a", "b"]}))
        self.assertFalse(is_valid(True, {"const": False}))
        self.assertEqual(validate([1, "x"], {"type": "array", "items": {"type": "integer"}}),
                         ["$[1]: expected type integer, got str"])

    def test_anyof_oneof(self):
        any_of = {"anyOf": [{"type": "string"}, {"type": "null"}]}
        self.assertTrue(is_valid(None, any_of))
        self.assertFalse(is_valid(1, any_of))
        one_of = {"oneOf": [{"type": "integer"}, {"type": "number"}]}
        self.assertFalse(is_valid(1, one_of))  # matches both
        self.assertTrue(is_valid(1.5, one_of))

    def test_check_raises_with_all_errors(self):
        with self.assertRaises(ValidationError) as ctx:
            check({"b": 1}, {"type": "object", "properties": {"b": {"type": "string"}}, "required": ["a"]})
        self.assertEqual(len(ctx.exception.errors), 2)

    def test_empty_schema_accepts_anything(self):
        self.assertTrue(is_valid({"anything": [1, None]}, {}))

    def test_malformed_schema_type_is_a_bug_not_a_validation_result(self):
        with self.assertRaises(ValueError):
            validate("x", {"type": "strng"})


if __name__ == "__main__":
    unittest.main()
