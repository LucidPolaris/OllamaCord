# OllamaCord
Standalone Discord chatbot using Ollama.

Behavior:
- Replies ONLY when the bot is @mentioned (ignores prefixed commands).
- Reply is prefixed by mentioning the user who invoked the bot: @SomeUser <AI reply>
- /reset: reset conversation context (public response)
- /toggle [enable]: enable/disable/toggle chatbot (public response)
- Slash commands are registered GLOBALLY (not guild-specific). Note: global command
  propagation can take up to ~1 hour after the first sync (Discord limitation).

Prerequisites:

Python 3.10+ recommended.

A Discord bot token (create a bot in the Discord Developer Portal).

The bot must be invited with the bot and applications.commands scopes so it can register slash commands.

Required Python packages: listed in requirements.txt.
