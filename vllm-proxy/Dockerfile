FROM golang:1.21-alpine AS builder

WORKDIR /app

# Install dependencies first for better caching
COPY go.mod go.sum ./
RUN go mod download

# Copy source code and build
COPY main.go .
RUN CGO_ENABLED=0 GOOS=linux go build -o vllm-proxy main.go

# Final lightweight stage
FROM alpine:3.18
WORKDIR /app
COPY --from=builder /app/vllm-proxy .

EXPOSE 8080

CMD ["./vllm-proxy"]
