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
   export OPENAI_API_KEY="your-openai-api-key"   # optional
   export POKETWO_BOT_ID="the-poketwo-bot-user-id"
   ```

   `POKETWO_BOT_ID` identifies the account whose spawn messages the bot
   monitors. Generated catch commands target `<@716390085896962058>`.

   Optionally set `ALLOWED_CHANNEL_IDS` to a comma-separated list of channels
   where the bot should respond, for example
   `ALLOWED_CHANNEL_IDS="123456789012345678,234567890123456789"`. Leave it unset
   to allow every channel the bot can access. Existing setups can keep using
   `ALLOWED_CHANNEL_ID` for one channel; do not set both variables.
   Or set `ALLOWED_CATEGORY_IDS` (comma-separated) to cover every channel in
   those categories, including threads under them. Channel and category lists
   can be combined; a channel matching either is allowed.
   The bot queues spawn recognition and processes up to 199 vision requests
   concurrently by default. Set `MAX_CONCURRENT_VISION_REQUESTS` to adjust this
   between 1 and 199 for your OpenAI project’s rate limits; the client retries
   temporary API errors.
   A larger channel count does not increase OpenAI API quota, so billing,
   project limits, and the exact error in the bot logs still matter if requests
   continue to fail. `OPENAI_MODEL` can select another vision-capable
   Chat Completions model.

4. Start the bot:

   ```sh
   python bot.py
   ```

The bot also handles spawns whose image or text Pokétwo adds by editing the message, processes each spawn message once, and retries temporary image-download or recognition failures up to three times before replying with an error.

To test an image manually, post it with `v!test` as the message caption. A
Missingno match immediately posts a staff warning.
Other test matches never send a catch command.
After a Missingno match (real or `v!test`), Vivillon ignores further Pokétwo messages
and edits in that channel until someone sends a `v!r` command there. This only
silences Vivillon's processing. Vivillon also denies Pokétwo's Send Messages
permission in that channel (needs Manage Permissions) so no more spawns appear,
and `v!r` restores it.

Image analysis uses `low` detail by default for faster naming; set `OPENAI_IMAGE_DETAIL` to `high` or `auto` for more accuracy on look-alike Pokémon. For speed, OpenAI fetches the spawn image directly from its URL (the bot only downloads and uploads it itself if that fails), and model replies are capped at 60 tokens.

When Pokétwo posts a wild-spawn image, the bot replies with one predicted name
and its estimated confidence percentage (for example, `Pikachu: 85.00%`). The
confidence is a model estimate, not a calibrated probability. The vision model
compares visible traits such as silhouette, proportions, face, colors, and
markings to identify Pokémon across the National Pokédex and distinguish similar
species and forms. Image recognition can still make mistakes, so check guesses
before relying on them. It then posts the
matching Pokétwo catch command as inline code for easier copying, preceded by a
bold “Copy Here >” label. A separate desktop copy card below it shows “Catch
[Pokémon]”, “Copy Below”, and the Pokétwo catch command. Discord displays both
formats on mobile and desktop.
Discord's copy controls depend on the client; the bot cannot directly write to a user's
clipboard. Pure Ice, Grass, Fire, Water, Normal, and Electric spawns use their custom emojis inline with the guessed name and no embed. Configured paired types that include any of those types show both corresponding custom emojis inline. Other configured type matches show their icons beside the guessed name in an embed, with the catch command in the embed description. Other dual-type Pokémon keep the regular text reply. Reservation, shinyhunt, and collection mentions remain active for both reply styles. Pokétwo or Discord may ignore or restrict commands sent by
another bot account. If the prediction is `Missingno.` or `???`, the bot sends
asks for a staff member; it does not send a catch command for that spawn.

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
reports their current selection. Use `v!sh remove absol` to remove your own
shinyhunt for that Pokémon, or `v!sh remove all arceus` to remove your all-forms
shinyhunt; this does not affect other members. When a matching Pokémon spawns, registered
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
reservation takes precedence over shinyhunt and collection mentions. Otherwise,
the bot shows a `Shinyhunt:` line and/or a `Collection:` line only for groups
with matching members. If no one matches, it shows the normal naming reply
without empty mention lines.

## Exchanging reservations

Reserve managers can move one member's reservations to others. Post a list
with one member per line (commas separate Pokémon, and `all <pokemon>` works):

```
@jade - pikachu, eevee
@bluebird - sylveon, hatterene
@snowii - all arceus
```

Then reply to that message with `v!r e @owner` (or `v!r exchange @owner`). The
bot shows an embed ("You want to exchange from @owner to those users") with
**Yes** and **No** buttons. **Yes** replies "Reserves exchanged." and moves each
listed Pokémon that `@owner` has reserved to the member on its line; **No**
replies "Exchange cancelled." If `@owner` doesn't have some listed Pokémon, small
text under the list names them and suggests "Do you mean @member?" for members
who do have them. Only the command user (with the reserve manager role) can
press the buttons (they appear even when `@owner` has none of the listed Pokémon), and unanswered prompts expire after 3 minutes.

In an exchange, `all <pokemon>` moves every form the owner has reserved, including regional forms such as Galarian or Alolan ones, not only the all-forms reservation.

Reserve lists (`v!r search @member`, `v!r list`) and the exchange prompt show an all-forms reservation as each form separately (for example, each Urshifu form) when form data is available. Species without form data still show as "all forms of <pokemon>".

## Grabbing a list with `v!grab`

Reply to any message or embed that contains Pokémon names, with `v!grab`: a `v!r search` result, a plain list, or a labelled list such as `Regional — @user - Zorua`. The bot finds the Pokémon names on each line (ignoring labels, emojis and formatting); the list shows only Pokémon names, and the `@user` on each line is remembered for Add reserves. Names come from `pokemon_names.json`. The bot builds
a separate list of every Pokémon (not just the visible page), all in one message with no page limit. Only the person who ran `v!grab` can use its buttons:

- **Order** – sorts the list alphabetically (click again to restore the original order).
- **All forms off / on** – turns green when on and puts `All` in front of
  Pokémon that have alternate forms.
- **Custom emoji** – opens a box for emojis separated by commas; they are put in
  front of the Pokémon in order and repeat (emoji 1, emoji 2, emoji 1, ...).
- **Copy** – sends you the current list (with the order, All forms and emojis as shown) as a plain private message containing only the list, with any emojis added through Custom emoji, so you can copy it directly. Discord doesn't let bots write to your clipboard directly. Custom server emojis stay as text and display once pasted.
- **Add reserves** – reserve managers only, and only when the list has an `@user`
  behind the Pokémon (`pikachu - @user1`). Shows an embed of which Pokémon goes to which user and asks "Are you sure you want to add all
  reserves?" with Yes/No; Yes adds each Pokémon to its user like `v!r add`
  (using `all <pokemon>` where All forms is on). Pokémon without an `@user` are skipped. After Yes, the bot posts each reserve as two separate messages, one at a time: `v!r add <pokemon> @user`, then `<Pokémon> added to @user` (without pinging anyone). Large lists take a while because Discord rate-limits message sending.

After a bot restart, `v!grab` on an old search message only sees the page shown in it.

## Org bot API

Vivillon can expose a small HTTP API so your org bot can manage reserves. It is off unless you set:

| Variable | Meaning |
| --- | --- |
| `ORG_BOT_API_KEY` | Secret the org bot sends as `Authorization: Bearer <key>`. Enables the API. |
| `ORG_GUILD_ID` | Server whose Vivillon reserves the org bot adds to / removes from. |
| `ORG_API_PORT` | Port to listen on (falls back to `PORT`, then `8080`). The host must expose this port publicly. |
| `ORG_RESERVES_FILE` | Optional. Org list file, default `org_reserves.json`. |
| `ORG_RESTRICTIONS_FILE` | Optional. Slot rules, default `org_restrictions.json`. |

Restriction file (optional; slots without a rule allow anything):

```json
{"slots": {"slot1": {"allowed": ["Pikachu", "Eevee"]}, "slot2": {"blocked": ["Mewtwo"]}}}
```

All requests need the `Authorization` header and return JSON with `"success"`. Errors use `{"success": false, "error": "..."}`: `400` invalid request, `401` unauthorized, `403` not allowed in that slot, `404` Pokémon not found / not reserved.

- `GET /api/org/health` needs no key; open it in a browser to check the URL works (`{"success": true, "status": "ok"}`).
- `POST /api/org/validate` with `{"pokemon": "Pikachu", "slot": "slot1"}` checks the name exists and the slot allows it. `slot` is optional; `"All Eevee"` is accepted for all forms.
- `POST /api/org/reserves` with `{"action": "add" or "remove", "pokemon": "Pikachu", "userId": "123456789012345678", "slot": "slot1"}` validates, then adds/removes the reserve in the org list and in Vivillon's saved reserves (same as `v!r add`). Success: `{"success": true, "action": "add", "pokemon": "Pikachu", "userId": "...", "slot": "slot1", "changed": true}`.
- `GET /api/org/reserves` lists the org's reserves: `{"success": true, "count": 1, "reserves": [{"pokemon": "Pikachu", "userId": "...", "slot": "slot1"}]}`. Use this for `!res list`.
- `POST /api/org/reset` (for `!org start`) clears the org list only; Pokémon already saved in Vivillon's reserves are kept.

Example:

```
curl -X POST https://YOUR-HOST:PORT/api/org/reserves \
  -H "Authorization: Bearer YOUR_KEY" -H "Content-Type: application/json" \
  -d '{"action":"add","pokemon":"Pikachu","userId":"123456789012345678"}'
```

## Reference images (faster recognition)

Put each Pokémon's spawn pictures in its own folder inside `pokemon_images/`, named exactly like the Pokémon (`pokemon_images/Abomasnow/`, `pokemon_images/Mega Absol/`). The file names inside don't matter. Use real spawn images Pokétwo posts, ideally with different backgrounds (about 10 to 25 each).

You can place a bulk archive of per-Pokémon image folders anywhere under `pokemon_images/` (for example `pokemon_images/archive/`). The builder searches recursively, merges duplicate folders, skips ambiguous composite images, and recognizes species, known forms, regional forms and event-costume names. Raw archive images are git-ignored; only upload the generated bank.

Build the feature file after adding images:

```
python build_image_bank.py
```

This writes `image_bank.npz`. Only the changed Pokémon are recomputed on later runs (cached in `.bank_cache/`). The bot loads `image_bank.npz` at startup (or the file in `IMAGE_BANK_FILE`), so the pictures themselves don't need to be on the host. Upload `image_bank.npz`, `image_match.py` and `bot.py`, then restart.

Reference-image matching checks both the original and horizontally flipped
spawn image, so Pokémon can be recognized facing either direction without
adding flipped copies to the image bank.

When a spawn is clearly one of the known Pokémon (the Pokémon's own features are matched, the background is ignored), the bot names it in about 60 ms without calling OpenAI (shown as 100.00%). Anything unclear falls back to OpenAI, or is skipped if there is no key. This needs `numpy` and `opencv-python-headless` (in `requirements.txt`).

`OPENAI_API_KEY` is optional. Without it the bot names spawns only from the reference images and stays silent (it logs `No reference image matched`) for any spawn that doesn't match, so add pictures for every Pokémon you want named.
