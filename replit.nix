
{ pkgs }: {
  deps = [
    pkgs.python311
    pkgs.python311Packages.fastapi
    pkgs.python311Packages.uvicorn
    pkgs.python311Packages.aiohttp
    pkgs.python311Packages.pandas
    pkgs.python311Packages.beautifulsoup4
    pkgs.python311Packages.python-multipart
  ];
}
