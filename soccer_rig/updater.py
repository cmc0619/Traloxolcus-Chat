import httpx

from .config import settings
from .models import UpdateApplyResponse, UpdateCheckResponse


GITHUB_API = "https://api.github.com/repos/{repo}/releases/latest"


def check_for_update() -> UpdateCheckResponse:
    url = GITHUB_API.format(repo=settings.update_repo)
    try:
        response = httpx.get(url, timeout=3)
    except httpx.HTTPError as exc:
        return UpdateCheckResponse(
            current_version=settings.version,
            available_version=None,
            can_update=False,
            message=f"update check failed: {exc}",
        )

    if response.status_code != 200:
        return UpdateCheckResponse(
            current_version=settings.version,
            available_version=None,
            can_update=False,
            message=f"github returned {response.status_code}",
        )

    data = response.json()
    latest = data.get("tag_name") or data.get("name") or data.get("id")
    can_update = bool(latest) and latest != settings.version
    return UpdateCheckResponse(
        current_version=settings.version,
        available_version=latest if can_update else None,
        can_update=can_update,
        message="new release available" if can_update else "already current",
    )


def apply_update(recording_active: bool) -> UpdateApplyResponse:
    if recording_active:
        return UpdateApplyResponse(started=False, message="Recording in progress; cannot update", applied_version=None)

    check = check_for_update()
    if not check.can_update or not check.available_version:
        return UpdateApplyResponse(started=False, message=check.message or "Already on latest release", applied_version=None)

    message = (
        "Update download staged. This would fetch from GitHub releases, verify checksums, and restart services."
    )
    return UpdateApplyResponse(started=True, message=message, applied_version=check.available_version)
