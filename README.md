# My Local Cinema 🎬
A lightweight movie library manager that organizes, tags, and serves your collection using metadata from [TMDb](https://www.themoviedb.org/). Supports flexible directory layouts, API authentication, and special handling for archived files.

## Features
- Fetches posters, metadata, and tags from TMDb.
- Customizable directory structure.
- Command line options for flexibility.
- Special **archived media handling**: files in `0-ARCHIVED` get tagged differently so you can keep them accessible without mixing them into your active collection.

## Quick Start
```bash
git clone https://github.com/IceMuppet/My-Local-Cinema.git
cd My-Local-Cinema
npm install             # or: pip install -r requirements.txt
npm start               # or: node server.js
```
Then open: http://localhost:3000

## Directory Structure
The server expects **4 active-content directories** plus an archive:

```text
/My-Local-Cinema
├── Movies/
├── Shows/
├── Standup/
├── Documentary/
└── 0-ARCHIVED/   # Holds archived media; handled with special tags
```

- Place standard content in `Movies`, `Shows`, `Standup`, or `Documentary`.
- Anything in `0-ARCHIVED` is marked as archived and separated in listings.

## Setup & Installation
Clone the repo and install dependencies:

```bash
git clone https://github.com/IceMuppet/My-Local-Cinema.git
cd My-Local-Cinema
npm install   # or: pip install -r requirements.txt
```

## Running the Server
Start the server with:

```bash
npm start
```

Or directly:

```bash
node server.js
```

Default port is `3000`. Open your browser at http://localhost:3000.

## Authentication (TMDb API)
This project requires a TMDb API token or Bearer key.

1. Create a TMDb account and generate an API key / Bearer token.
2. Add it to your environment:

```bash
export TMDB_API_KEY=your_api_key_here
export TMDB_BEARER=your_bearer_token_here
```

You can also provide them at runtime (see CLI options below).

## Command Line Parameters
You can customize behavior using flags:

```bash
node server.js [options]
```

**Options:**
- `--port <number>` – set the server port (default: `3000`)
- `--tmdb-key <key>` – pass TMDb API key directly
- `--tmdb-bearer <token>` – pass TMDb bearer token directly
- `--media-dir <path>` – set the root directory for media
- `--no-cache` – disable caching of TMDb results
- `--verbose` – enable detailed logging

**Example:**

```bash
node server.js --port 8080 --tmdb-bearer "your_token" --media-dir ~/Movies
```

## How It Works
1. The script scans the **four required directories** (`Movies`, `Shows`, `Standup`, `Documentary`) and the special `0-ARCHIVED` directory.
2. Files are matched against TMDb using the API key/bearer provided.
3. Posters and metadata are cached locally.
4. Items inside `0-ARCHIVED` are tagged as archived so they don’t mix into your active lists.

## Contributing
Pull requests are welcome! Please open an issue to discuss changes before submitting a PR.

## License
MIT License © 2025 [IceMuppet](https://github.com/IceMuppet)
