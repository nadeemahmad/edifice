"""Read Google Drive metadata through an nflx-google OAuth token."""

import base64
import json
import os
import socket
import subprocess
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from typing import Any, cast

import click

from edifice.document_library import DriveDocument


class NflxGoogleSource:
    """Provide live Drive metadata using the current employee OAuth token."""

    def __init__(
        self,
        *,
        token_path: Path | None = None,
        metatron_binary: str = "metatron",
    ) -> None:
        self._token_path = token_path or _default_token_path()
        self._metatron_binary = metatron_binary
        self._drive: Any | None = None

    def get_document(self, source_id: str) -> DriveDocument:
        value = (
            self._drive_client()
            .files()
            .get(
                fileId=source_id,
                fields=_document_fields(),
                supportsAllDrives=True,
            )
            .execute()
        )
        return _drive_document(cast(dict[str, object], value))

    def recently_viewed(
        self,
        *,
        days: int,
        limit: int,
    ) -> tuple[DriveDocument, ...]:
        viewed_after = datetime.now(UTC) - timedelta(days=days)
        value = (
            self._drive_client()
            .files()
            .list(
                q=(
                    f"viewedByMeTime > '{viewed_after.isoformat()}' and trashed = false"
                ),
                pageSize=limit,
                orderBy="viewedByMeTime desc",
                fields=f"files({_document_fields()})",
            )
            .execute()
        )
        files = cast(dict[str, object], value).get("files", [])
        if not isinstance(files, list):
            raise click.ClickException("Google Drive returned an invalid file list.")
        documents: list[DriveDocument] = []
        for item in cast(list[object], files):
            if isinstance(item, dict):
                documents.append(_drive_document(cast(dict[str, object], item)))
        return tuple(documents)

    def _drive_client(self) -> Any:
        if self._drive is not None:
            return self._drive
        token = _load_token(self._token_path, self._metatron_binary)
        try:
            credentials_type = import_module("google.oauth2.credentials").Credentials
            credentials = credentials_type.from_authorized_user_info(token)
            build = import_module("googleapiclient.discovery").build
            identity = build("oauth2", "v2", credentials=credentials)
            user = identity.userinfo().get().execute()
            typed_user = cast(dict[str, object], user) if isinstance(user, dict) else {}
            email = typed_user.get("email")
            if not isinstance(email, str) or not email.endswith("@netflix.com"):
                raise click.ClickException(
                    "nflx-google is not authenticated with a Netflix account."
                )
            self._drive = build("drive", "v3", credentials=credentials)
        except click.ClickException:
            raise
        except Exception as error:
            raise click.ClickException(
                f"Cannot initialize nflx-google Drive access: {error}"
            ) from error
        return self._drive


def create_nflx_google_source() -> NflxGoogleSource:
    """Create the configured live work-document source."""
    configured = os.environ.get("EDIFICE_NFLX_GOOGLE_TOKEN")
    token_path = Path(configured).expanduser() if configured else None
    return NflxGoogleSource(
        token_path=token_path,
        metatron_binary=os.environ.get("EDIFICE_METATRON_BIN", "metatron"),
    )


def _default_token_path() -> Path:
    hostname = (
        os.environ.get("BD_HOSTNAME")
        or os.environ.get("HOSTNAME")
        or socket.gethostname()
    ).split(".")[0]
    return Path.home() / ".config" / "nflx-google" / f"token-{hostname}.json"


def _load_token(path: Path, metatron_binary: str) -> dict[str, object]:
    try:
        stored = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise click.ClickException(
            f"Cannot read nflx-google token: {path}. Run nflx-google login first."
        ) from error
    try:
        value: object = json.loads(stored)
    except json.JSONDecodeError:
        try:
            encrypted = base64.b64decode(stored, validate=True)
            result = subprocess.run(
                [metatron_binary, "decryptbundle"],
                input=encrypted,
                capture_output=True,
                check=False,
            )
        except (OSError, ValueError) as error:
            raise click.ClickException(
                "Cannot decrypt the nflx-google token."
            ) from error
        if result.returncode != 0:
            raise click.ClickException("Cannot decrypt the nflx-google token.")
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise click.ClickException(
                "Decrypted nflx-google token is invalid."
            ) from error
    if not isinstance(value, dict):
        raise click.ClickException("Invalid nflx-google token.")
    return cast(dict[str, object], value)


def _document_fields() -> str:
    return (
        "id,name,mimeType,modifiedTime,viewedByMeTime,"
        "sharedWithMeTime,version,webViewLink"
    )


def _drive_document(value: dict[str, object]) -> DriveDocument:
    required = ("id", "name", "mimeType", "webViewLink")
    if any(not isinstance(value.get(field), str) for field in required):
        raise click.ClickException("Google Drive returned invalid document metadata.")
    return DriveDocument(
        source_id=cast(str, value["id"]),
        source_url=cast(str, value["webViewLink"]),
        title=cast(str, value["name"]),
        mime_type=cast(str, value["mimeType"]),
        modified_at=_optional_string(value.get("modifiedTime")),
        viewed_at=_optional_string(value.get("viewedByMeTime")),
        shared_at=_optional_string(value.get("sharedWithMeTime")),
        version=_optional_string(value.get("version")),
    )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None
