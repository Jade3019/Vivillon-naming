# Vivillon-naming

A Discord application bot that recognizes Pokétwo spawn images with OpenAI
vision, replies with the predicted Pokémon name, and summarizes level, gender,
and IV information found in Pokétwo messages.

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

When Pokétwo posts a wild-spawn image, the bot sends the recognized name as a
reply. The vision model is asked to identify Pokémon across the National
Pokédex; image recognition can still make mistakes, so check guesses before
relying on them.

After a catch, the bot summarizes level, gender, and IV data that appear in
Pokétwo's message. If a catch message omits IV or gender, run Pokétwo's usual
Pokémon-info command yourself; the bot will summarize the fields it can read
from the resulting Pokétwo message. It does not issue game commands on your
behalf.

Pokétwo or Discord may ignore or restrict messages from other bot accounts.
This application does not bypass those restrictions.
