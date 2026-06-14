from opendata_campus_mcp.mcp_server.server import build_server


def main() -> None:
    server = build_server()
    server.run()


if __name__ == "__main__":
    main()
