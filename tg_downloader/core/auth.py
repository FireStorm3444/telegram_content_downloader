"""Authentication lifecycle manager supporting phone login, SMS/app code, and 2FA password."""

import logging

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from telethon import TelegramClient, errors
from telethon.tl import types

from tg_downloader.config import Settings
from tg_downloader.core.errors import AuthenticationError

logger = logging.getLogger(__name__)


class AuthManager:
    """Manages Telegram authentication, interactive login, 2FA, and session cleanup."""

    def __init__(
        self,
        client: TelegramClient,
        settings: Settings,
        console: Console | None = None,
    ) -> None:
        self.client = client
        self.settings = settings
        self.console = console or Console()

    async def is_authorized(self) -> bool:
        """Check if current session is authorized."""
        if not self.client.is_connected():
            await self.client.connect()
        return bool(await self.client.is_user_authorized())

    async def get_user_info(self) -> types.User | None:
        """Fetch current authenticated user object, or None if unauthorized."""
        if not await self.is_authorized():
            return None
        me = await self.client.get_me()
        if isinstance(me, types.User):
            return me
        return None

    async def ensure_authorized(self) -> types.User:
        """Ensure client is authorized; start interactive login flow if not."""
        if not self.client.is_connected():
            await self.client.connect()

        if await self.client.is_user_authorized():
            user = await self.client.get_me()
            if isinstance(user, types.User):
                return user

        return await self.login_interactive()

    async def login_interactive(self) -> types.User:
        """Execute interactive authentication lifecycle with code and 2FA prompt."""
        if not self.client.is_connected():
            await self.client.connect()

        if await self.client.is_user_authorized():
            me = await self.client.get_me()
            if isinstance(me, types.User):
                self.console.print(
                    Panel(
                        f"[bold green]Already Authenticated![/]\n"
                        f"User: [bold]{me.first_name or ''} {me.last_name or ''}[/]\n"
                        f"Username: @{me.username or 'None'}\n"
                        f"Phone: +{me.phone or 'Hidden'}\n"
                        f"User ID: [cyan]{me.id}[/]",
                        title="[bold green]Telegram Session Active[/]",
                        border_style="green",
                    )
                )
                return me

        self.console.print(
            Panel(
                "[bold cyan]Telegram Interactive Authentication[/]\n"
                "Please enter your login details to connect to MTProto.",
                border_style="cyan",
            )
        )

        phone = self.settings.phone
        if not phone:
            phone = Prompt.ask(
                "[bold yellow]Phone number[/] (international format, e.g. [green]+1234567890[/])",
                console=self.console,
            ).strip()

        try:
            sent_code = await self.client.send_code_request(phone)
            self.console.print(
                f"[green]✓[/] Verification code sent to Telegram app/SMS on [bold]{phone}[/]."
            )
        except errors.FloodWaitError as e:
            raise AuthenticationError(
                f"Telegram FloodWait: please wait {e.seconds} seconds before attempting login again."
            ) from e
        except Exception as e:
            raise AuthenticationError(f"Failed to send code request to {phone}: {e}") from e

        code = Prompt.ask(
            "[bold yellow]Verification code[/]",
            console=self.console,
        ).strip()

        try:
            user = await self.client.sign_in(phone, code, phone_code_hash=sent_code.phone_code_hash)
        except errors.SessionPasswordNeededError:
            self.console.print("[yellow]Two-Step Verification (2FA) is enabled on this account.[/]")
            password = Prompt.ask(
                "[bold yellow]2FA Password[/]",
                password=True,
                console=self.console,
            )
            try:
                user = await self.client.sign_in(password=password)
            except Exception as e:
                raise AuthenticationError(f"2FA sign-in failed: {e}") from e
        except Exception as e:
            raise AuthenticationError(f"Telegram sign-in failed: {e}") from e

        if isinstance(user, types.User):
            self.console.print(
                Panel(
                    f"[bold green]Successfully Authenticated![/]\n"
                    f"User: [bold]{user.first_name or ''} {user.last_name or ''}[/]\n"
                    f"Username: @{user.username or 'None'}\n"
                    f"User ID: [cyan]{user.id}[/]",
                    title="[bold green]Login Successful[/]",
                    border_style="green",
                )
            )
            return user

        raise AuthenticationError("Authenticated entity is not a Telegram User.")

    async def logout(self) -> None:
        """Log out from Telegram and remove local session file."""
        if not self.client.is_connected():
            await self.client.connect()

        if await self.client.is_user_authorized():
            try:
                await self.client.log_out()
                self.console.print("[green]✓[/] Successfully logged out from Telegram servers.")
            except Exception as e:
                logger.warning("Error logging out from server: %s", e)

        await self.client.disconnect()

        # Remove local session file
        session_file = self.settings.session_path
        if session_file.exists():
            session_file.unlink()
            self.console.print(f"[green]✓[/] Removed local session file: [cyan]{session_file}[/]")
