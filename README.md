<div align="center">
<img src="https://raw.githubusercontent.com/EChistov/ydl_bot/main/.github/logo-editor-cropped.svg" alt="ydl_bot_logo" style="width:200px;"/>
</div>

# YDL_BOT

## The Telegram Bot which can make an mp3-file from a YouTube link

##### "By using this bot or its code, you take full responsibility for its usage. The author created this pet project for self-learning and does not assume any responsibility for its use."

## Key features

- Download and convert any YouTube video to mp3, and possibly other services (support connected to [yt-dlp](https://github.com/yt-dlp/yt-dlp) and not
  tested).
- Based on the duration of the source video, the bot sets up suitable bitrate and sends the file via a 50 MB Telegram API default
  window (a version of the bot with Docker-composed self-hosted Telegram API without these file sending restrictions could be available
  later).
- Privilege system with Users (who can only download and convert files) and Admins (who can grant users and admins
  privileges and look up the history).
- Useful status bars for the downloading and converting processes.

## How to use

Just copy a YouTube link or share it with the bot. After a few seconds, if you have the right privileges, the bot starts
the downloading and converting process.

The bot sends the file to you (up to **50 MB** in size) and it also tries to use a lower bitrate if the MP3 file will have a size
bigger than 50 MB. Most interview-style videos less than 2 hours long sound very well with this option. *This is an API restriction
that can be solved using a local copy of the API. Maybe later versions of the bot will have this option.*

Use the `/admin` command or the Telegram bot menu near the input field to add or delete users or admins. If you don't
see the admin keyboard, something has gone wrong with your privileges.

## Installation

The installation process requires `docker`. You can run the app as-is, using Python 3.18 and above, but you should also 
install `ffmpeg`. 

*Notice: The bot is intended for a **small number of users**, file conversion using ffmpeg is very resource-intensive.*

Usually, the process contains 4 steps:

- Clone and build the image.
- Get a Telegram API key using [BotFather](https://t.me/botfather) (https://core.telegram.org/bots/features#botfather).
- Run the bot in init mode to get your Telegram user ID.
- Run the bot in normal mode.

### Get an API key

- Open Telegram, find [`@BotFather`](https://t.me/botfather) bot. 
- Follow the instructions to set your bot name and receive an API key.

### Clone and build the Docker image

The easiest way to install and run this bot is by using Docker. Use the `Dockerfile` from this repository. You should know
your Telegram user ID to add yourself to the SuperAdmin list. The bot supports special init mode to get your ID.

- Clone the repository.
- Run `touch database.db` in the project root folder. If you do not do this and
  add `-v $(pwd)/database.db:/opt/ydl_bot/app/database.db` in the run command, you will get an error about access to the
  database file.
- Build the container by running the `docker build .` command in the project **root** folder.

```commandline
git clone https://github.com/EChistov/ydl_bot.git
cd ydl_bot/
touch database.db
docker build . -t ydl_bot:0.1
```

### Getting your user id by running bot in init mode

The init mode runs **automatically** when you do not provide any **user id** in the environment
variable `BOT_SUPERADMIN_LIST` or in the `"super_admin_list"` directive of the config file `bot_conf.json`. If you
already have your Telegram user id, please skip this step and just set up the environment variable in the `docker run`
command.

**Please do not forget to replace `<Put your telegram api token here>` with your real token.**

Go to the project root and run:

```commandline
docker run -v $(pwd)/bot_conf.json:/opt/ydl_bot/bot_conf.json \
           -v $(pwd)/mp3:/opt/ydl_bot/mp3  \
           -v $(pwd)/database.db:/opt/ydl_bot/app/database.db \
           -e TELEGRAM_TOKEN=<Put your telegram api tocken here> \
           -it ydl_bot:0.1
```

- Find your bot on Telegram and press start to collect your ID.
- Stop the container. If you do not do this, it will conflict with the second run using the same API token.

### Run the bot in normal mode

- Insert your ID into the environment variable `BOT_SUPERADMIN_LIST` or into the bot config file `bot_conf.json` (I
  recommend using the environment variable way).
  It is a list, and you can provide multiple IDs separated by `,`.
- Run the bot in daemon mode using this command in the project **root**. **Please use it with your token and user ID**.

```commandline
docker run -v $(pwd)/bot_conf.json:/opt/ydl_bot/bot_conf.json \
           -v $(pwd)/mp3:/opt/ydl_bot/mp3  \
           -v $(pwd)/database.db:/opt/ydl_bot/app/database.db \
           -e TELEGRAM_TOKEN=<Put your telegram api tocken here> \
           -e BOT_SUPERADMIN_LIST=<your telegram id> \
           -itd ydl_bot:0.1
```

Your Telegram ID must be placed in the environment variable or the config file as SuperAdmin. SuperAdmins cannot be
deleted from the bot interface; they are the first admins who have access to the admin menu of the bot.

## Update

Keep the bot up to date; sometimes something goes wrong with the YouTube API. Usually, a new version
of [yt_dlp](https://github.com/yt-dlp/yt-dlp) solves this problem. The version of yt_dlp is not fixed in
requirements.txt.

Just fetch new changes from the repo and remake the Docker container.

## User Privileges

The Bot has 4 privilege levels:

- User (can only convert videos to MP3s)
- Admin (can add/delete users/admins, but can't delete a SuperAdmin)
- SuperAdmin (it is an admin from the `"super_admin_list"` directive of the config file or ENV `BOT_SUPERADMIN_LIST` (it
  is a list, and you can provide multiple IDs separated by `,`). A SuperAdmin has the same privileges as an admin but
  can't be deleted from the UI.
- Unauthorised (shows only user ID)

**You have to set up at least one SuperAdmin using the config or System Environment.**
If you run the bot without any ID in `"super_admin_list"` or System Environment, the bot runs in Unauthorised mode
even if there are a few admins in the DB.
