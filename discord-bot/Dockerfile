FROM python:3.13-slim-bookworm
WORKDIR /gridmii

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY gridbot ./gridbot
RUN mkdir data

CMD ["python", "-m", "gridbot"]