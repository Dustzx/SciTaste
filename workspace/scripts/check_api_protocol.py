"""CPU checks for GT separation, image identity, and strict deterministic scoring."""
import tempfile
from pathlib import Path

from bailian_blink_dev import parse_answer, vision_message, sha, ROOT

def main():
    assert parse_answer("FINAL: (B)", ["x", "y"]) == "B"
    assert parse_answer("FINAL: (C)", ["x", "y"]) is None
    assert parse_answer("FINAL: (A)\nFINAL: (B)", ["x", "y"]) is None
    assert parse_answer("The answer may be A or B", ["x", "y"]) is None
    assert parse_answer("(A)", ["x", "y"]) == "A"
    with tempfile.NamedTemporaryFile(dir=ROOT, suffix=".img") as handle:
        handle.write(b"test_image_content")
        handle.flush()
        sample = {"prompt": "Which object?", "images": [{"path": str(Path(handle.name).relative_to(ROOT)),
                  "sha256": sha(b"test_image_content"), "mime": "image/png"}]}
        msg = vision_message(sample, "test instruction")
        assert len(msg["content"]) == 4 and msg["content"][-1]["text"] == "test instruction"
        try:
            vision_message(dict(sample, answer="GT_SENTINEL"), "test")
        except AssertionError:
            pass
        else:
            raise AssertionError("GT allowed into inference")
        sample["images"][0]["sha256"] = "wrong"
        try:
            vision_message(sample, "test")
        except AssertionError:
            pass
        else:
            raise AssertionError("Changed image silently accepted")
    print("8 protocol checks passed; zero API calls")

if __name__ == "__main__":
    main()
