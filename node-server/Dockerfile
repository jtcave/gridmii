FROM alpine:latest AS build-stage
RUN apk upgrade
RUN apk add build-base mosquitto-dev
WORKDIR /gridmii
COPY *.c /gridmii/
COPY *.h /gridmii/
COPY Makefile /gridmii/
WORKDIR /gridmii
RUN make

FROM alpine:latest AS final-stage
RUN apk upgrade
RUN apk add mosquitto-libs
WORKDIR /gridmii
COPY --from=build-stage /gridmii/gm-node /gridmii/gm-node
COPY start_node.sh /gridmii/
RUN mkdir /gridmii/data

ENV NODE_BIN=/gridmii/gm-node
WORKDIR /gridmii/data
CMD ["/gridmii/start_node.sh", "gm-node.conf"]