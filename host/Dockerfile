FROM python:3.13-slim-trixie
WORKDIR /gridmii

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# oci is a soft dependency so install it separately
RUN pip install --no-cache-dir oci

COPY gridbot ./gridbot
RUN mkdir data

CMD ["python", "-m", "gridbot"]