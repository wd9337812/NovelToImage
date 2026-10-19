import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("comic", ROOT / "skills/zhihu-comic-cpa/scripts/comic.py")
comic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comic)


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = comic.load_config()
        cls.plan = comic.read_json(ROOT / "examples/plan.json")
        cls.story = (ROOT / "examples/story.txt").read_text(encoding="utf-8")
        cls.temp_root = ROOT / "runs" / "test-tmp"
        cls.temp_root.mkdir(parents=True, exist_ok=True)

    def test_plan_requires_real_source_anchors_and_exact_keyword(self):
        comic.validate_plan(self.plan, "雨夜来信", 5, 2, self.story)
        for title, quote in [("错误关键词", None), ("雨夜来信", "这句原文不存在")]:
            plan = copy.deepcopy(self.plan)
            if quote:
                plan["pages"][0]["panels"][0]["source_quote"] = quote
            with self.assertRaises(comic.ComicError):
                comic.validate_plan(plan, title, 5, 2, self.story)

    def test_refuses_unknown_speaker_overlong_text_and_extra_character(self):
        for field, value in [("texts", [{"type": "dialogue", "speaker": "未知人物", "text": "你好"}]),
                             ("texts", [{"type": "narration", "text": "长" * 47}]),
                             ("characters", ["unknown"])]:
            plan = copy.deepcopy(self.plan)
            plan["pages"][0]["panels"][0][field] = value
            with self.assertRaises(comic.ComicError):
                comic.validate_plan(plan, "雨夜来信", 5, 2, self.story)

    def test_mock_album_complete_and_cache_resume(self):
        with tempfile.TemporaryDirectory(dir=self.temp_root) as folder:
            archive = comic.create_album(self.plan, self.story, self.cfg, folder, mock=True)
            self.assertEqual(archive.name, "MOCK-layout.zip")
            first = comic.read_json(archive.parent / "manifest.json")
            self.assertEqual(first["count"], 5)
            self.assertEqual(first["generated_this_run"], 8)
            with zipfile.ZipFile(archive) as zf:
                self.assertEqual(len(zf.namelist()), 11)
                self.assertIsNone(zf.testzip())
                self.assertFalse(any(x.startswith(".cache") or x.endswith(".env") for x in zf.namelist()))
                self.assertNotIn(self.story.encode(), zf.read("storyboard.json"))
            archive2 = comic.create_album(self.plan, self.story, self.cfg, folder, mock=True)
            self.assertEqual(archive, archive2)
            second = comic.read_json(archive.parent / "manifest.json")
            self.assertEqual(second["generated_this_run"], 0)
            self.assertEqual(second["cached_this_run"], 8)
            self.assertEqual(comic.main(["verify", str(archive.parent)]), 0)
            image = archive.parent / "images/02.png"
            image.write_bytes(b"corrupted")
            self.assertFalse(comic.verify_images(archive.parent, second)["passed"])

    def test_changed_plan_never_reuses_old_run_and_failures_do_not_package(self):
        with tempfile.TemporaryDirectory(dir=self.temp_root) as folder:
            with self.assertRaises(comic.ComicError):
                comic.create_album(self.plan, self.story, self.cfg, folder, mock=True, max_calls=1)
            self.assertEqual(list(Path(folder).rglob("*.zip")), [])
            failed = next(Path(folder).glob("*/run.json"))
            self.assertEqual(comic.read_json(failed)["status"], "failed")
            archive = comic.create_album(self.plan, self.story, self.cfg, folder, mock=True)
            self.assertEqual(comic.read_json(archive.parent / "manifest.json")["cached_this_run"], 1)
            changed = copy.deepcopy(self.plan)
            changed["hook"] = "雨夜里的第二封信"
            other = comic.create_album(changed, self.story, self.cfg, folder, mock=True)
            self.assertNotEqual(archive.parent, other.parent)

    def test_http_401_stops_without_echoing_provider_secrets(self):
        client = comic.Client(self.cfg)
        response = Mock(status_code=401, ok=False, text="provider echoed SECRET_VALUE")
        with patch.dict(os.environ, AGNES_API_KEY="fake-test-only"), patch.object(client.session, "post", return_value=response) as post:
            with self.assertRaises(comic.ComicError) as error:
                client.post("image", {"prompt": "test"})
            self.assertEqual(post.call_count, 1)
            self.assertNotIn("SECRET_VALUE", str(error.exception))
            self.assertFalse(post.call_args.kwargs["allow_redirects"])

    def test_bounded_retry_and_reference_request(self):
        client = comic.Client(self.cfg)
        bad = Mock(status_code=429, ok=False, headers={"Retry-After": "1"})
        good = Mock(status_code=200, ok=True)
        good.json.return_value = {"data": []}
        with patch.dict(os.environ, AGNES_API_KEY="fake-test-only"), patch.object(client.session, "post", side_effect=[bad, good]) as post, patch.object(comic.time, "sleep"):
            result = client.post("image", {})
            self.assertEqual(result, {"data": []})
            self.assertEqual(post.call_count, 2)
        raw = comic.make_mock("test", comic.font_path(self.cfg))
        import base64
        with patch.object(client, "post", return_value={"data": [{"b64_json": base64.b64encode(raw).decode()}]}) as post:
            self.assertTrue(client.image("a scene", raw).startswith(b"\x89PNG"))
            self.assertTrue(post.call_args.args[1]["image"][0].startswith("data:image/png;base64,"))

    def test_planner_repairs_bad_source_quote_once_then_validates(self):
        client = comic.Client(self.cfg)
        invalid = copy.deepcopy(self.plan)
        invalid["pages"][0]["panels"][0]["source_quote"] = "模型自行改写的无效原文"
        responses = [{"choices": [{"message": {"content": json.dumps(p, ensure_ascii=False)}}]} for p in (invalid, self.plan)]
        with patch.object(client, "post", side_effect=responses) as post:
            actual = client.plan("雨夜来信", self.story, 5, 2)
            self.assertEqual(actual["title"], "雨夜来信")
            self.assertEqual(post.call_count, 2)
        with patch.object(client, "post", return_value=responses[0]) as post:
            with self.assertRaises(comic.ComicError):
                client.plan("雨夜来信", self.story, 5, 2)
            self.assertEqual(post.call_count, 2)

    def test_rejects_remote_http_and_bad_or_small_image(self):
        for url in ["http://example.com/v1", "https://user:pass@example.com/v1", "https://example.com/v1?token=secret"]:
            with self.assertRaises(comic.ComicError):
                comic.check_api_url(url)
        with self.assertRaises(comic.ComicError):
            comic.normalize_image(b"not an image")
        client = comic.Client(self.cfg)
        with self.assertRaises(comic.ComicError):
            client.download("http://127.0.0.1/private")

    def test_partial_config_replaces_extra_and_rejects_embedded_secret(self):
        with tempfile.TemporaryDirectory(dir=self.temp_root) as folder:
            file = Path(folder) / "config.json"
            comic.save_json(file, {"image": {"provider": "openai", "extra": {"quality": "low"}}})
            cfg = comic.load_config(file)
            self.assertEqual(cfg["image"]["extra"], {"quality": "low"})
            comic.save_json(file, {"image": {"api_key": "should-not-be-in-a-file"}})
            with self.assertRaises(comic.ComicError):
                comic.load_config(file)


if __name__ == "__main__":
    unittest.main()
