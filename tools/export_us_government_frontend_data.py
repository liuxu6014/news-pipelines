"""Export the standalone NIH and White House dataset for the shared frontend."""

import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "us_government_news" / "us_government_news.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "run_reports" / "us_government_news" / "us_government_news_data.js"
DEFAULT_JSON_OUTPUT = PROJECT_ROOT / "run_reports" / "us_government_news" / "us_government_news.json"


def export_frontend_data(input_path=DEFAULT_INPUT, output_path=DEFAULT_OUTPUT, json_output_path=DEFAULT_JSON_OUTPUT):
    payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
    output = {
        "generated_at": payload.get("generated_at", ""),
        "items": payload.get("items", []),
        "sources": payload.get("sources", []),
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "window.US_GOVERNMENT_NEWS_DATA = "
        + json.dumps(output, ensure_ascii=False, indent=2)
        + ";\n",
        encoding="utf-8",
    )
    json_output_path = Path(json_output_path)
    json_output_path.parent.mkdir(parents=True, exist_ok=True)
    json_output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return len(output["items"]), output_path, json_output_path


def main():
    parser = argparse.ArgumentParser(description="Export existing NIH and White House data for index.html.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--json-output", default=str(DEFAULT_JSON_OUTPUT))
    args = parser.parse_args()
    count, output, json_output = export_frontend_data(args.input, args.output, args.json_output)
    print(f"Exported {count} U.S. government news items to {output}")
    print(f"Saved JSON copy to {json_output}")


if __name__ == "__main__":
    main()
