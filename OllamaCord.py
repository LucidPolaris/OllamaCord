import asyncio
import logging
from typing import List, Dict, Optional

import discord
from discord.ext import commands
import ollama

# ------------------------ Configuration ------------------------ #

BOT_TOKEN = "YOUR_DISCORD_BOT_TOKEN_HERE"  # <-- replace with your bot token

DEFAULT_MODEL_NAME = "DEFAULT_MODEL_NAME"

# Conversation/file limits
MAX_CONVERSATION_LOG_SIZE = 50
MAX_TEXT_ATTACHMENT_SIZE = 20_000
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB

# ------------------------ Logging ------------------------ #

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s › %(message)s")
logger = logging.getLogger("discord_ollama_bot")

# ------------------------ Ollama Wrapper ------------------------ #


class OllamaAssistant:
    """
    Lightweight Ollama wrapper.

    The system_prompt can be updated at runtime (useful to include the bot's username).
    """

    DEFAULT_SYSTEM_PROMPT_TEMPLATE = (
        "You are {bot_name}, a helpful but slightly offhand assistant residing in Discord. "
        "Answer the user's questions directly. You may be playful or roast lightly, "
        "but do not be abusive or discriminatory."
    )

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        timeout: float = 120.0,
    ):
        self.model_name = model_name
        # if system_prompt is None, it will be set later via set_system_prompt_with_botname()
        self.system_prompt = system_prompt or self.DEFAULT_SYSTEM_PROMPT_TEMPLATE.format(bot_name="Abstruse")
        self.temperature = temperature
        self.timeout = timeout
        self._client_timeout = timeout

    def set_system_prompt_with_botname(self, bot_name: str):
        """Update the system prompt so it contains the bot's username."""
        self.system_prompt = self.DEFAULT_SYSTEM_PROMPT_TEMPLATE.format(bot_name=bot_name)

    def initial_conv_logs(self) -> List[Dict[str, str]]:
        """Return the default conversation log (system prompt)."""
        return [{"role": "system", "content": self.system_prompt}]

    async def chat(self, messages: List[Dict[str, str]]) -> str:
        """
        Send messages to Ollama and return assistant content.
        Creates an ollama.AsyncClient per call (sufficient for light usage).
        """
        client = ollama.AsyncClient(timeout=self._client_timeout)
        try:
            coro = client.chat(
                model=self.model_name,
                messages=messages,
                options={"temperature": self.temperature},
            )
            res = await asyncio.wait_for(coro, timeout=self.timeout)
            return res.get("message", {}).get("content", "") or "No response."
        except asyncio.TimeoutError:
            return "AI request timed out."
        except Exception as e:
            logger.exception("Ollama error")
            return f"AI error: {e}"


# ------------------------ Discord Bot ------------------------ #

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
assistant = OllamaAssistant()

# Global chat enabled flag (True => bot replies when mentioned)
bot._chat_enabled = True

def is_text_file(data: bytes) -> bool:
    try:
        data.decode("utf-8")
        return True
    except Exception:
        return False


async def send_in_chunks(channel: discord.abc.Messageable, text: str, **kw):
    for i in range(0, len(text), 2000):
        await channel.send(text[i : i + 2000], **({} if i else kw))


@bot.event
async def on_ready():
    # set assistant system prompt to include the actual bot username
    try:
        bot_name = bot.user.name
        assistant.set_system_prompt_with_botname(bot_name)
        # initialize conversation logs so the system prompt is in place
        bot._conv_logs = assistant.initial_conv_logs()
        logger.info("Assistant system prompt set to include bot name: %s", bot_name)
    except Exception:
        logger.exception("Failed to set assistant system prompt with bot name.")

    # register global slash commands (may take up to ~1 hour to propagate to clients)
    if not getattr(bot, "_synced_commands", False):
        try:
            await bot.tree.sync()  # global sync
            bot._synced_commands = True
            logger.info("Globally synced slash commands.")
        except Exception:
            logger.exception("Failed to globally sync slash commands.")

    logger.info(f"Bot ready as {bot.user} (id: {bot.user.id})")


@bot.event
async def on_message(message: discord.Message):
    # ignore messages from bots
    if message.author.bot:
        return

    # still allow normal prefixed commands (not used here mostly)
    await bot.process_commands(message)

    # Only respond when bot is explicitly mentioned, chatbot is enabled, and message is not a prefixed "!" command
    if not bot._chat_enabled:
        return

    if bot.user.mentioned_in(message) and not message.content.startswith("!"):
        st = getattr(bot, "_conv_logs", assistant.initial_conv_logs())

        # Process small text attachments
        txt = ""
        for att in message.attachments:
            if att.size > MAX_FILE_SIZE:
                await message.channel.send(f"{att.filename} is too large (max {MAX_FILE_SIZE} bytes).")
                return
            data = await att.read()
            if not is_text_file(data):
                await message.channel.send(f"{att.filename} is not a text file.")
                return
            txt_part = data.decode("utf-8")[:MAX_TEXT_ATTACHMENT_SIZE]
            txt += "\n\n" + txt_part

        # Append the user's message
        st.append({"role": "user", "content": message.content + txt})

        async with message.channel.typing():
            reply = await assistant.chat(st)

        # Append assistant reply
        st.append({"role": "assistant", "content": reply})

        # Trim conversation if needed (keep system prompt at index 0)
        while len(st) > MAX_CONVERSATION_LOG_SIZE:
            st.pop(1)

        bot._conv_logs = st

        # Prefix reply by mentioning the user (this pings them)
        user_mention = message.author.mention
        await send_in_chunks(message.channel, f"{user_mention} {reply}", reference=message)


@bot.tree.command(name="reset", description="Reset the AI conversation context for this bot.")
async def reset(interaction: discord.Interaction):
    """Reset conversation logs back to the system prompt (public response)."""
    bot._conv_logs = assistant.initial_conv_logs()
    await interaction.response.send_message("AI context reset.", ephemeral=False)


@bot.tree.command(name="toggle", description="Enable, disable, or toggle the chatbot replies.")
async def toggle(interaction: discord.Interaction, enable: Optional[bool] = None):
    """
    Toggle the chatbot on/off.
    - If `enable` is provided (true/false), set that state.
    - If omitted, flip the current state.
    The response is non-ephemeral (public).
    """
    current = getattr(bot, "_chat_enabled", True)
    if enable is None:
        new_state = not current
    else:
        new_state = bool(enable)
    bot._chat_enabled = new_state
    state_str = "enabled" if new_state else "disabled"
    await interaction.response.send_message(f"Chatbot {state_str}.", ephemeral=False)


# ------------------------ Entrypoint ------------------------ #

def main():
    if BOT_TOKEN == "YOUR_DISCORD_BOT_TOKEN_HERE":
        logger.error("You must replace BOT_TOKEN with your bot token before running.")
        return
    bot.run(BOT_TOKEN)


if __name__ == "__main__":
    main()
