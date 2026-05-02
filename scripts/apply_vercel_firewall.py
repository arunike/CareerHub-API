import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parents[1]
PROJECT_FILE = BASE_DIR / ".vercel" / "project.json"
FIREWALL_ACTIONS_FILE = BASE_DIR / "vercel-firewall-actions.json"
VERCEL_FIREWALL_URL = "https://api.vercel.com/v1/security/firewall/config"


def main():
    token = os.environ.get("VERCEL_TOKEN", "").strip()
    if not token:
        print("VERCEL_TOKEN is required.", file=sys.stderr)
        return 1

    project = json.loads(PROJECT_FILE.read_text())
    actions = json.loads(FIREWALL_ACTIONS_FILE.read_text())
    query = urlencode({"projectId": project["projectId"], "teamId": project["orgId"]})
    url = f"{VERCEL_FIREWALL_URL}?{query}"

    for action in actions:
        body = json.dumps(action).encode("utf-8")
        request = Request(
            url,
            data=body,
            method="PATCH",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            print(f"Failed action {action.get('action')}: HTTP {exc.code} {detail}", file=sys.stderr)
            return 1
        print(f"Applied {action.get('action')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
