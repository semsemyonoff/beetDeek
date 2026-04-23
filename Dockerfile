FROM python:3.14-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

COPY app.py /app/app.py
COPY src /app/src

RUN mkdir -p /tmp/beetdeck && chmod 1777 /tmp/beetdeck

WORKDIR /app
EXPOSE 5000
ENV TMPDIR=/tmp/beetdeck

CMD ["gunicorn", "-b", "0.0.0.0:5000", "-w", "1", "--threads", "4", "--worker-tmp-dir", "/tmp/beetdeck", "app:app"]
