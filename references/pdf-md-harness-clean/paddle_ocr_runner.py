#!/usr/bin/env python3
"""Run PaddleOCR's Korean model on rendered page images."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("images", nargs="+", type=Path)
    return parser.parse_args()


def main() -> int:
    from paddleocr import PaddleOCR

    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    ocr = PaddleOCR(
        lang="korean",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )

    for image in args.images:
        predictions = ocr.predict(str(image))
        result = predictions[0] if isinstance(predictions, list) else next(predictions)
        texts = list(result.get("rec_texts", []))
        scores = [float(score) for score in result.get("rec_scores", [])]
        output = args.output_dir / f"{image.stem}.txt"
        output.write_text("\n".join(texts) + "\n", encoding="utf-8")
        (output.with_suffix(".json")).write_text(
            json.dumps(
                {
                    "image": str(image),
                    "lines": len(texts),
                    "mean_confidence": sum(scores) / len(scores) if scores else 0.0,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
