FROM golang:1.23-alpine3.20 AS build

ENV CGO_ENABLED=0

WORKDIR /src

COPY . .

RUN go build -o /go/bin/bff

FROM jrottenberg/ffmpeg:7-ubuntu

COPY --from=build /go/bin/bff /usr/local/bin/bff

RUN apt-get update && apt-get upgrade -y && apt-get install sox -y

ENTRYPOINT [""]

CMD ["/usr/local/bin/bff"]
