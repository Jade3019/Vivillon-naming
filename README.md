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
and its estimated confidence percentage (for example, `Pikachu: 85.00%`). The
confidence is a model estimate, not a calibrated probability. The vision model
compares visible traits such as silhouette, proportions, face, colors, and
markings to identify Pokémon across the National Pokédex and distinguish similar
species and forms. Image recognition can still make mistakes, so check guesses
before relying on them. It then posts the
matching Pokétwo catch command as inline code for easier copying. Discord's
copy controls depend on the client; the bot cannot directly write to a user's
clipboard. Pure Ice-type Pokémon show only the Ice icon; pure Grass-type Pokémon show only the Grass icon; pure Electric-type Pokémon show only the Electric icon; pure Water-type Pokémon show only the Water icon; pure Fire-type Pokémon show only the Fire icon; pure Normal-type
Pokémon show only the Normal icon. Pokémon with exactly Ice and Electric,
Normal and Ice, Ice and Water, Ice and Fire, Fire and Normal, Normal and Water,
Water and Fire, Fire and Electric, Electric and Water, Electric and Normal, Grass and Fire, Grass and Water,
Grass and Normal, or Grass and Electric as their two types show both icons.
Type-matched spawns show the icon beside the guessed name in an embed, with the
catch command in the embed description. Other dual-type Pokémon keep the regular text
reply. Reservation, shinyhunt, and collection mentions remain active for both
reply styles. Pokétwo or Discord may ignore or restrict commands sent by
another bot account. If the prediction is `Missingno.` or `???`, the bot sends
the Pokétwo `inc p` command, waits 500 milliseconds, and asks for a staff
member; it does not send a catch command for that spawn.

This application does not bypass those restrictions.

## Pokémon reservations

Any server member can view reservations with `v!r list`, search who reserved a
Pokémon with `v!r search pikachu`, or see one member's reserved Pokémon with
`v!r search @member`. Use `v!r search all arceus` to list Arceus by type
(for example, `fairy arceus @member`) and show the reservers for each type.
Use `v!r search all pichu` for its regular and spiky-eared forms. This catalog
covers alternate forms across Pokémon and excludes regional variants. Results
with multiple pages show previous/next arrow buttons beneath the embed. The
catalog in `pokemon_forms.json` is a static snapshot based on the
[PokeAPI CSV data](https://github.com/PokeAPI/pokeapi/tree/master/data/v2/csv).
To regenerate it, download `pokemon.csv`, `pokemon_forms.csv`,
`pokemon_species.csv`, and `pokemon_types.csv` into one directory and run
`python generate_pokemon_forms.py <csv-directory>`.

Only members with the reserve-manager role (role ID `1532820386511720579`) can
change reservations. They can reserve Pokémon for a server member with:

```text
v!r add pikachu, eevee @member
v!r add all arceus @member
```

Use `all <pokemon>` to reserve every form of that Pokémon; the member is then
mentioned when any matching form spawns. More than one member can reserve the
same Pokémon. When a reserved Pokémon spawns, the bot lists and mentions its
reserved members in a `Reserved:` line above the catch command. The
`Reserved:` line is omitted when no one reserved that Pokémon. Other members
are not mentioned. Reservations are stored in
`reserves.json` by default; set `RESERVES_FILE` to a different path if needed.
Keep that file on persistent host storage to retain reservations across
restarts. The bot must be able to read and send messages in the command channel
as well as the spawn channel.

Members with the reserve-manager role can remove reservations with
`v!r remove pikachu, eevee @member` or `v!r remove pikachu, eevee, @member` to
remove them only from that member's reserves, or
`v!r remove pikachu, eevee` to remove those Pokémon's reservations for everyone
in the current server. Use `v!r remove all arceus @member` to remove that
member's all-forms reservation. A single Pokémon name can still be used in
either command.
Successful member-specific removals reply with `Pikachu, Eevee removed from
@member Reserves`.

Use `v!r clear` to clear every reservation in the current server. The bot asks
for confirmation with Yes and No buttons; Yes clears the server's reservations,
and No cancels the command.

Any server member can select one Pokémon to shinyhunt with `v!sh absol`, or
track every non-regional form with `v!sh all arceus`. A new selection replaces
their previous shinyhunt in that server. Running `v!sh` without a Pokémon name
reports their current selection. When a matching Pokémon spawns, registered
hunters are mentioned in a `Shinyhunt:` line. If the Pokémon has a reservation,
the existing `Reserved:` mentions take precedence over shiny-hunt mentions.
Shiny-hunt registrations are stored in `shinyhunts.json` by default; set
`SHINYHUNTS_FILE` to use a different path.

Any server member can add Pokémon to their collection with
`v!cl add pikachu, eevee`, remove one or more with `v!cl remove pikachu, eevee`,
clear their own collection in the current server with `v!cl clear`, and view
their list with `v!cl list`. Removing Pokémon from a collection leaves other
members' entries intact. Adding a Pokémon that is already in your collection
reports that it is already added and does not create a duplicate. Collection
entries are stored in `collections.json`
by default; set `COLLECTIONS_FILE` to use a different path. The list is
paginated at 20 Pokémon per page with previous/next buttons. On a spawn, a
reservation takes precedence over both shinyhunt and collection mentions;
otherwise the bot shows both `Shinyhunt:` and `Collection:` lines when either
group has a matching member.
