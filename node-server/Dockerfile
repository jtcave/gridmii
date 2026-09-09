FROM alpine:latest AS deps
RUN apk upgrade
RUN apk add build-base openssl3-dev jansson-dev

FROM deps AS build-stage
COPY src/ /gridmii/src/
COPY src/version.h /gridmii/src/version.h
COPY Makefile /gridmii/
WORKDIR /gridmii
RUN sed -i '/git/d' Makefile
RUN sed -i '/GIT/d' Makefile
RUN sed -i 's/-fsanitize=address//' Makefile
RUN make

FROM alpine:latest AS final-stage
RUN apk upgrade
RUN apk add openssl3 jansson
WORKDIR /gridmii
COPY --from=build-stage /gridmii/bin/gm-node /gridmii/gm-node
COPY start_node.sh /gridmii/
RUN mkdir /gridmii/data

ENV NODE_BIN=/gridmii/gm-node
WORKDIR /gridmii/data
CMD ["/gridmii/start_node.sh", "gm-node.conf"]