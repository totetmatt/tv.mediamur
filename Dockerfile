FROM python:3
MAINTAINER @totetmatt
ENTRYPOINT python main.py

COPY req.txt /req.txt
RUN pip install -r req.txt
WORKDIR /app

COPY templates/ /app/templates
COPY settings.py  /app/settings.py 
COPY main.py /app/main.py  


