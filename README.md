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
matching Pokétwo catch command as inline code for easier copying. Discord's
copy controls depend on the client; the bot cannot directly write to a user's
clipboard. Pokétwo or Discord may ignore or restrict commands sent by another
bot account.

This application does not bypass those restrictions.

## Pokémon reservations

Only members with the reserve-manager role (role ID `1532820386511720579`) can
use the `v!r` commands. They can reserve Pokémon for a server member with:

```text
v!r add pikachu, eevee @member
```

More than one member can reserve the same Pokémon. Use `v!r search @member` to see that
member's reservations in an embed. When a reserved Pokémon spawns, the bot
lists and mentions its reserved members in a `Reserved:` line above the catch
command. The `Reserved:` line is omitted when no one reserved that Pokémon.
Other members are not mentioned. Reservations are stored in
`reserves.json` by default; set `RESERVES_FILE` to a different path if needed.
Keep that file on persistent host storage to retain reservations across
restarts. The bot must be able to read and send messages in the command channel
as well as the spawn channel.

Members with the reserve-manager role can remove reservations with
`v!r remove pikachu, eevee @member` or `v!r remove pikachu, eevee, @member` to
remove them only from that member's reserves, or
`v!r remove pikachu, eevee` to remove those Pokémon's reservations for everyone
in the current server. A single Pokémon name can still be used in either command.
Successful member-specific removals reply with `Pikachu, Eevee removed from
@member Reserves`.

Use `v!r clear` to clear every reservation in the current server. The bot asks
for confirmation with Yes and No buttons; Yes clears the server's reservations,
and No cancels the command.

Any server member can select one Pokémon to shinyhunt with `v!sh absol`. A new
selection replaces their previous shinyhunt in that server. The command replies
with `You are currently shinyhunting absol`; running `v!sh` without a Pokémon
name reports their current selection. When it spawns, registered hunters are
mentioned in a `Shinyhunt:` line. If the Pokémon has a reservation, the existing
`Reserved:` mentions take precedence over shiny-hunt mentions. Shiny-hunt
registrations are stored in `shinyhunts.json` by default; set `SHINYHUNTS_FILE`
to use a different path.
