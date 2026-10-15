# Vivillon-naming

A Discord application bot that recognizes Pokétwo spawn images with OpenAI
vision and replies with the predicted Pokémon name and confidence percentage.

## Requirements

- Python 3.10 or newer
- A Discord application/bot token
- An OpenAI API key (vision requests may incur API costs)
- The Pokétwo bot ID for the server where you will use the bot

Spawn images are sent to OpenAI for recognition.

This project uses a regular Discord bot account, not a user-account self-bot.
Enable **Message Content Intent** for your application in the Discord Developer
Portal, invite it to your server with permission to read and send messages, and
ensure it can view the channel where Pokétwo spawns appear. Discord may require
approval for privileged intents on larger bots.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

   ```sh
   python -m pip install -r requirements.txt
   ```

3. Set the required environment variables:

   ```sh
   export DISCORD_TOKEN="your-discord-bot-token"
   export OPENAI_API_KEY="your-openai-api-key"
   export POKETWO_BOT_ID="the-poketwo-bot-user-id"
   ```

   Optionally set `ALLOWED_CHANNEL_ID` to limit the bot to one channel and
   `OPENAI_MODEL` to select another vision-capable Chat Completions model.

4. Start the bot:

   ```sh
   python bot.py
   ```

When Pokétwo posts a wild-spawn image, the bot replies with one predicted name
and its estimated confidence percentage (for example, `Pikachu: 85%`). The
confidence is a model estimate, not a calibrated probability. The vision model
is asked to identify Pokémon across the National Pokédex; image recognition can
still make mistakes, so check guesses before relying on them. It then posts the
matching Pokétwo catch command in a code block for easier copying. Discord's
copy controls depend on the client; the bot cannot directly write to a user's
clipboard. Pokétwo or Discord may ignore or restrict commands sent by another
bot account.

This application does not bypass those restrictions.

## Pokémon reservations

Members with the reserve-manager role (role ID `1532820386511720579`) can
reserve a Pokémon for a server member with:

```text
v!r add pikachu @member
```

More than one member can reserve the same Pokémon. When that Pokémon spawns,
the bot lists and mentions its reserved members in a `Reserved:` line above the
catch command. Other members are not mentioned. Reservations are stored in
`reserves.json` by default; set `RESERVES_FILE` to a different path if needed.
Keep that file on persistent host storage to retain reservations across
restarts. The bot must be able to read and send messages in the command channel
as well as the spawn channel.
