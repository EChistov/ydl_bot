FROM python:3.8-alpine
RUN apk add --update --no-cache build-base
# ENV TELEGRAM_TOKEN=""
COPY ./app /opt/ydl_bot/app/
COPY ./requirements.txt /opt/ydl_bot/
RUN apk -U add ffmpeg
RUN pip install --upgrade pip
RUN pip install --upgrade setuptools
RUN pip install -r /opt/ydl_bot/requirements.txt

#Uncomment to get the latest yt-dlp
# RUN pip install --force-reinstall https://github.com/yt-dlp/yt-dlp/archive/master.tar.gz

RUN mkdir opt/ydl_bot/mp3
WORKDIR /opt/ydl_bot/app
CMD ["python", "youtube_bot.py"]