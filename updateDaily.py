
import os
import sys
import random
from io import BytesIO

import requests

# Environment variables from GitHub Actions Secrets
COOKIES = os.environ.get("NAUKRI_COOKIES", "")
FILE_ID = os.environ.get("GOOGLE_DRIVE_FILE_ID", "")
FORM_KEY = os.environ.get("NAUKRI_FORM_KEY", "")

HEADERS = {
    "accept": "application/json",
    "appid": "105",
    "clientid": "d3skt0p",
    "systemid": "jobseeker",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


def parse_cookies(cookie_str):
    cookies = {}
    for pair in cookie_str.split(";"):
        if "=" in pair:
            key, value = pair.strip().split("=", 1)
            cookies[key.strip()] = value.strip()
    return cookies


def refresh_token(session, refresh_token_val):
    """Diagnose the existing refresh endpoint without printing secrets."""
    url = (
        "https://www.naukri.com/"
        "central-login-services/v1/login/token/refresh"
    )

    print("[DEBUG] Sending token refresh request...")

    try:
        resp = session.post(
            url,
            headers={
                **HEADERS,
                "content-type": "application/json",
            },
            json={"refreshToken": refresh_token_val},
            timeout=30,
        )
    except requests.RequestException as exc:
        print(f"[ERROR] Refresh request failed: {type(exc).__name__}")
        return None

    print(f"[DEBUG] Refresh HTTP status: {resp.status_code}")
    print(f"[DEBUG] Response cookie names: {list(resp.cookies.keys())}")
    print(f"[DEBUG] Session cookie names: {list(session.cookies.keys())}")

    # Do not print response bodies: they may contain sensitive information.
    if resp.status_code != 200:
        print("[WARN] Refresh endpoint did not return HTTP 200.")
        return None

    # Some servers update the session cookies during refresh.
    token = session.cookies.get("nauk_at")

    if token:
        print("[OK] Access token found in session cookies.")
        return token

    print("[WARN] HTTP 200, but no nauk_at cookie was found.")
    return None


def get_profile_id(session, token):
    url = (
        "https://www.naukri.com/"
        "cloudgateway-mynaukri/resman-aggregator-services/"
        "v0/users/self/dashboard"
    )

    resp = session.get(
        url,
        headers={
            **HEADERS,
            "authorization": f"Bearer {token}",
        },
        timeout=30,
    )

    print(f"[DEBUG] Dashboard HTTP status: {resp.status_code}")

    if resp.status_code != 200:
        print("[ERROR] Dashboard request failed.")
        resp.raise_for_status()

    data = resp.json()
    profile_id = (
        data.get("dashBoard", {}).get("profileId")
        or data.get("profileId")
    )

    if not profile_id:
        raise RuntimeError("Profile ID was not found in dashboard response.")

    return profile_id


def download_pdf(file_id):
    url = f"https://drive.google.com/uc?export=download&id={file_id}"

    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    if not resp.content.startswith(b"%PDF"):
        raise RuntimeError(
            "Downloaded content is not a PDF. Check the Drive file ID "
            "and sharing permissions."
        )

    return resp.content


def upload_file(pdf_bytes, filename, form_key):
    file_key = "U" + "".join(
        random.choice(
            "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        )
        for _ in range(13)
    )

    resp = requests.post(
        "https://filevalidation.naukri.com/file",
        headers={
            "appid": "105",
            "systemid": "fileupload",
        },
        files={
            "file": (filename, BytesIO(pdf_bytes), "application/pdf")
        },
        data={
            "formKey": form_key,
            "fileName": filename,
            "fileKey": file_key,
        },
        timeout=60,
    )

    print(f"[DEBUG] File upload HTTP status: {resp.status_code}")
    resp.raise_for_status()

    return file_key


def attach_to_profile(session, token, profile_id, form_key, file_key):
    url = (
        "https://www.naukri.com/cloudgateway-mynaukri/"
        "resman-aggregator-services/v0/users/self/profiles/"
        f"{profile_id}/advResume"
    )

    resp = session.post(
        url,
        headers={
            **HEADERS,
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
            "x-http-method-override": "PUT",
        },
        json={
            "textCV": {
                "formKey": form_key,
                "fileKey": file_key,
                "textCvContent": None,
            }
        },
        timeout=60,
    )

    print(f"[DEBUG] Attach resume HTTP status: {resp.status_code}")
    resp.raise_for_status()


def main():
    if not all([COOKIES, FILE_ID, FORM_KEY]):
        print(
            "[ERROR] Missing one or more GitHub Secrets: "
            "NAUKRI_COOKIES, GOOGLE_DRIVE_FILE_ID, NAUKRI_FORM_KEY"
        )
        sys.exit(1)

    session = requests.Session()
    cookies = parse_cookies(COOKIES)

    for key, value in cookies.items():
        session.cookies.set(key, value, domain=".naukri.com")

    print(f"[DEBUG] Initial cookie names: {list(cookies.keys())}")

    # Try refreshing first, then use the existing access token if available.
    token = cookies.get("nauk_at")
    refresh_value = cookies.get("nauk_rt")

    if refresh_value:
        new_token = refresh_token(session, refresh_value)

        if new_token:
            token = new_token
            print("[OK] Token refreshed.")
        else:
            print(
                "[WARN] Refresh failed; checking the existing access token."
            )
    else:
        print("[WARN] No nauk_rt cookie was supplied.")

    if not token:
        print(
            "[ERROR] No access token available. "
            "Update the NAUKRI_COOKIES secret."
        )
        sys.exit(1)

    print("[INFO] Checking Naukri dashboard authentication...")

    try:
        profile_id = get_profile_id(session, token)
    except requests.RequestException:
        print(
            "[ERROR] Dashboard request failed. "
            "Check the status code above and verify your cookies."
        )
        sys.exit(1)

    print("[OK] Dashboard authentication succeeded.")
    print("[OK] Profile ID retrieved.")

    # Stop after diagnostics; no resume is uploaded in this test.
    print("[INFO] Diagnostic mode complete. No resume was uploaded.")


if __name__ == "__main__":
    main()
