import tempfile
import unittest
from pathlib import Path

from simorgh.ledger.api import BlobNotFound, ValidationError
from simorgh.ledger.blobs import InMemoryBlobStore, LocalBlobStore, is_ref, parse_ref, ref_for


class TestRefHelpers(unittest.TestCase):
    def test_ref_for_is_content_addressed(self):
        self.assertEqual(ref_for(b"x"), ref_for(b"x"))
        self.assertNotEqual(ref_for(b"x"), ref_for(b"y"))
        self.assertTrue(ref_for(b"x").startswith("blob:"))

    def test_is_ref_accepts_governing_and_legacy_forms(self):
        self.assertTrue(is_ref(ref_for(b"x")))
        self.assertTrue(is_ref("blob:sha256:" + "0" * 64))
        self.assertFalse(is_ref("not a ref"))
        self.assertFalse(is_ref(""))

    def test_parse_ref_rejects_malformed(self):
        with self.assertRaises(ValidationError):
            parse_ref("blob:tooshort")
        with self.assertRaises(ValidationError):
            parse_ref("not-a-blob-ref")


class TestInMemoryBlobStore(unittest.TestCase):
    def test_put_get_round_trip(self):
        store = InMemoryBlobStore()
        ref = store.put(b"hello", content_type="text/plain")
        self.assertEqual(store.get(ref), b"hello")

    def test_put_is_idempotent_for_identical_content(self):
        store = InMemoryBlobStore()
        ref1 = store.put(b"same", content_type="text/plain")
        ref2 = store.put(b"same", content_type="text/plain")
        self.assertEqual(ref1, ref2)
        self.assertEqual(store.stat()["blobs"], 1)

    def test_missing_blob_raises(self):
        store = InMemoryBlobStore()
        with self.assertRaises(BlobNotFound):
            store.get(ref_for(b"nope"))


class TestLocalBlobStore(unittest.TestCase):
    def test_put_get_round_trip_and_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalBlobStore(Path(tmp))
            ref1 = store.put(b"same content", content_type="text/plain")
            ref2 = store.put(b"same content", content_type="text/plain")
            self.assertEqual(ref1, ref2)
            self.assertEqual(store.get(ref1), b"same content")
            self.assertEqual(store.stat(), {"blobs": 1, "blob_bytes": len(b"same content")})

    def test_tamper_is_detected_via_digest_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalBlobStore(Path(tmp))
            ref = store.put(b"original", content_type="text/plain")
            digest = ref.split(":", 1)[1]
            path = Path(tmp) / digest[:2] / digest
            path.write_bytes(b"tampered!")
            with self.assertRaises(BlobNotFound):
                store.get(ref)

    def test_no_tmp_file_left_behind_after_a_successful_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalBlobStore(Path(tmp))
            store.put(b"data", content_type="text/plain")
            leftovers = list(Path(tmp).rglob("*.tmp"))
            self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
