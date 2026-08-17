import os
from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer
)


class MigrationHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        message = (
            "Database migration is in progress."
        ).encode("utf-8")

        self.send_response(200)
        self.send_header(
            "Content-Type",
            "text/plain; charset=utf-8"
        )
        self.send_header(
            "Content-Length",
            str(len(message))
        )
        self.end_headers()
        self.wfile.write(message)

    def log_message(self, format, *args):
        return


def main():
    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    server = ThreadingHTTPServer(
        ("0.0.0.0", port),
        MigrationHandler
    )

    print(
        f"Migration server listening on port {port}",
        flush=True
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()