class TorrentDownloader:
    def __init__(self, temp_dir: Path, torrent: Torrent): ...
    
    async def download_file(
        self,
        torrent_file: TorrentFile,     # нужный ZIP-архив
        inner_file_name: str,          # "{lib_id}.fb2"
        progress_cb: Callable | None = None,
    ) -> Path:
        """Скачать ZIP-архив, распаковать нужный файл, вернуть путь к .fb2."""