FROM python:3.10
RUN mkdir ~/bot
WORKDIR ~/bot
COPY . .
RUN apt-get -y update
RUN apt-get -y upgrade
RUN apt-get install -y ffmpeg
RUN pip install -r requirements.txt
CMD ["python", "bot.py"]