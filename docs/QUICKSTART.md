# Quick start

This takes you from a fresh clone to a reviewed, exported content package in about 10 minutes.

The app takes recordings and transcripts **only from MeetStream**, and uses **OpenAI** to find the best moments and write the content. Parts 1-4 need no API keys: a local stand-in plays MeetStream with a sample webinar, and the app runs without OpenAI in offline mode. Parts 5 and 6 switch on OpenAI and your real MeetStream account.

## What you need

| Requirement | Check | Install |
|---|---|---|
| Python 3.11+ | `python3 --version` | python.org, or `brew install python@3.12` |
| [uv](https://docs.astral.sh/uv/) (recommended) | `uv --version` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| FFmpeg with libass and libfreetype | `ffmpeg -filters \| grep subtitles` | `brew install ffmpeg` / `apt install ffmpeg` |
| macOS (only for the sample webinar) | `which say` | Elsewhere, skip Parts 2-4 and go straight to your MeetStream account (Parts 5-6) |

## Part 1: Install

```bash
cd meetstream-content-creation
uv venv
uv pip install -e ".[mcp,dev]"
```

Without uv: `python3 -m venv .venv && .venv/bin/pip install -e ".[mcp,dev]"`.

Check that it works:

```bash
.venv/bin/python -m pytest -q
```

You should see `36 passed`. The tests render real video with FFmpeg, so they take about 20 seconds.

## Part 2: Make a sample webinar

```bash
.venv/bin/python scripts/make_sample.py samples
```

This takes under a minute. You get:
- `samples/sample_webinar.mp4`: a ~4-minute "webinar" with two speakers, and slides for each section;
- `samples/sample_transcript.json`: its transcript, in MeetStream's own format.

The script uses macOS text-to-speech, so the voices sound robotic. The timings are exact, though, which is what matters here.

## Part 3: Run the app against a local MeetStream

Start the MeetStream stand-in. It serves the sample as a finished bot recording, through the same API routes as the real MeetStream:

```bash
.venv/bin/uvicorn --app-dir scripts demo_meetstream:app --port 8765
```

In a second terminal, start the app pointed at it:

```bash
MEETSTREAM_API_KEY=demo MEETSTREAM_BASE_URL=http://127.0.0.1:8765/api/v1 \
  .venv/bin/uvicorn contentfactory.api:app --reload
```

Open **http://127.0.0.1:8000**. The badge in the top right says **AI writing off**. That's expected: you haven't added an OpenAI key yet.

> **Offline mode** builds drafts with simple rules, mostly by picking and arranging sentences the speakers actually said. It lets you try the whole workflow, but the writing is not what the product produces with OpenAI.

## Part 4: Make, review and download a package

1. Paste `https://zoom.us/j/8812345678` into the big box. Underneath, it says **✓ Found the recording**: the latest of two recordings of that meeting.
2. Optionally open **Options** to set a title, the audience, tone and number of clips. Then click **Create content**.
3. A checklist shows each step as it happens. Offline, the whole thing takes about 30 seconds; most of that is FFmpeg cutting 4 clips in two formats.

Also try `https://meet.google.com/abc-defg-hij`: the bot is still in that meeting, so it says so straight away instead of creating anything.

When it's done you land on the review screen:
- **At the top:** how many items are approved, rejected and still to decide, and the **Download** button.
- **Check before publishing:** for example *"1 segment may contain confidential information"*. The sample says "this next part is not public yet" on purpose. Click the ▶ time to hear it.
- **On the left:** **To review** (everything waiting for a decision), then each content type with how many are approved.
- **In the middle:** one card per item, with **✓ Approve**, **Edit**, **Ask for changes** and **Reject**.
- **On the right:** the original recording and its transcript.

Try these:

| Do this | What happens |
|---|---|
| Play a clip, then switch it to **Vertical** | Captions are burned in; the vertical version is for Reels, Shorts and TikTok. |
| Click any ▶ time | The original recording plays from that moment, and the transcript line is highlighted. |
| **Edit** a clip and change where it starts or ends | Saving re-cuts the clip and its captions, and puts it back in **To review**. "Start at the player's position" sets it from the original recording. |
| **Edit** a quote and change a word | The save is refused: a quote must be word for word what the speaker said. |
| **Ask for changes** on a LinkedIn post | You type what should change. It can't be approved until someone edits it. |
| **Approve** a few items, **Reject** one | Approved items leave **To review** and the counts update. In a single content type, **Approve all** approves the rest of that type. |
| Click **Download** | The first time, it asks you to confirm the speakers agreed and you have the rights to the material. Then it downloads a ZIP. |

The ZIP has `manifest.json`, `blog.md` (if you approved the blog), the clips, captions and the transcript. Only approved assets are included. The manifest records who approved each one and when, plus file checksums.

## Part 5: Turn on OpenAI

Get an API key from https://platform.openai.com/api-keys. Then stop the app (leave the stand-in running) and run:

```bash
export OPENAI_API_KEY=sk-...
MEETSTREAM_API_KEY=demo MEETSTREAM_BASE_URL=http://127.0.0.1:8765/api/v1 \
  .venv/bin/uvicorn contentfactory.api:app --reload
```

The badge now reads **AI: gpt-6-astra**, and cards get a **Rewrite with AI** button. Generate a package from the same link again: OpenAI now picks the clips and actually writes the chapter titles, blog, posts and briefs. Expect a few minutes even for a short recording, most of it waiting on the model. The blog, posts and quotes are generated in parallel to keep that down.

To keep keys in a file instead:

```bash
cp .env.example .env    # then edit .env
set -a; source .env; set +a
```

## Part 6: Use your MeetStream account

1. Create a MeetStream API key at https://app.meetstream.ai/api-key.
2. Stop both servers, and start the app against the real MeetStream (no `MEETSTREAM_BASE_URL`):
   ```bash
   export MEETSTREAM_API_KEY=ms_...
   .venv/bin/uvicorn contentfactory.api:app --reload
   ```
3. On the home page, either:
   - paste the meeting's own Zoom / Google Meet / Teams link, a MeetStream link to the recording, or a bot id. It shows which recording it found. Or:
   - click **Pick from your recent recordings**.

   Then click **Create content**.

The app fetches the bot's transcript and video, falling back to audio if there's no video, then runs the same pipeline.

**For good video clips, the bot must have recorded video,** and for a transcript it needs a post-call transcription provider. MeetStream's REST API records video by default, but bots created through their MCP server are audio-only unless you ask for video. See [MEETSTREAM.md](MEETSTREAM.md#setting-up-bots-for-the-content-factory) for the recommended bot settings.

## Part 7 (optional): Use it from an AI agent

With the server still running:

```bash
claude mcp add content-factory -- "$(pwd)/.venv/bin/contentfactory-mcp"    # Claude Code; any MCP client works
```

Then, in the agent: *"List my MeetStream recordings and create a content package for the latest one, for a developer audience."* See [MCP.md](MCP.md).

## Where things are on disk

Everything lives under `./data` (change it with `CF_DATA_DIR`). Delete the folder to start fresh.

```
data/
  contentfactory.db                 jobs, assets, versions, reviews
  webinars/<id>/recording.mp4       the source recording
  webinars/<id>/transcript.json     the transcript every citation points into
  jobs/<id>/clips/*.mp4             rendered clips
  jobs/<id>/captions/*.srt|vtt      captions
  jobs/<id>/exports/*.zip           exported packages
```

## Next

- See the [API reference](API.md) to drive it from scripts.
- See [Review and export](REVIEW_AND_EXPORT.md) for every rule the review queue enforces.
- See [Troubleshooting](TROUBLESHOOTING.md) if a job fails.
