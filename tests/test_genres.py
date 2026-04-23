"""Tests for genres blueprint routes."""
from tests.conftest import insert_album, insert_item


# ---------------------------------------------------------------------------
# POST /api/album/<id>/genre  (fetch_genre_preview)
# ---------------------------------------------------------------------------


class TestFetchGenrePreview:
    def test_returns_404_when_album_not_found(self, client, mocker):
        mock_lib = mocker.MagicMock()
        mock_lib.get_album.return_value = None
        mocker.patch("src.routes.genres._init_beets", return_value=mock_lib)
        resp = client.post("/api/album/9999/genre")
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "Album not found"

    def test_returns_500_when_lastgenre_plugin_not_loaded(self, client, mocker):
        mock_album = mocker.MagicMock()
        mock_lib = mocker.MagicMock()
        mock_lib.get_album.return_value = mock_album
        mocker.patch("src.routes.genres._init_beets", return_value=mock_lib)
        mocker.patch("beets.plugins.find_plugins", return_value=[])
        resp = client.post("/api/album/1/genre")
        assert resp.status_code == 500
        assert resp.get_json()["error"] == "lastgenre plugin not loaded"

    def test_returns_old_and_new_genre(self, client, mocker):
        mock_album = mocker.MagicMock()
        mock_album.albumartist = "Artist"
        mock_album.album = "Album"
        mock_album.get.side_effect = lambda key, default="": {
            "genres": "Rock"
        }.get(key, default)
        mock_lib = mocker.MagicMock()
        mock_lib.get_album.return_value = mock_album
        mocker.patch("src.routes.genres._init_beets", return_value=mock_lib)

        mock_plugin = mocker.MagicMock()
        mock_plugin.name = "lastgenre"

        def side_effect_process(album, write):
            # Simulate plugin writing a new genre to album
            mock_album.get.side_effect = lambda key, default="": {
                "genres": "Electronic"
            }.get(key, default)

        mock_plugin._process.side_effect = side_effect_process
        mocker.patch("beets.plugins.find_plugins", return_value=[mock_plugin])

        resp = client.post("/api/album/1/genre")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "old_genre" in data
        assert "new_genre" in data

    def test_restores_genre_after_preview(self, client, mocker):
        mock_album = mocker.MagicMock()
        mock_album.albumartist = "Artist"
        mock_album.album = "Album"
        mock_album.get.return_value = "Rock"
        mock_lib = mocker.MagicMock()
        mock_lib.get_album.return_value = mock_album
        mocker.patch("src.routes.genres._init_beets", return_value=mock_lib)

        mock_plugin = mocker.MagicMock()
        mock_plugin.name = "lastgenre"
        mocker.patch("beets.plugins.find_plugins", return_value=[mock_plugin])

        client.post("/api/album/1/genre")

        # genres should have been set back to the original value and store() called
        assert mock_album.store.called

    def test_pretend_mode_is_reset_even_on_exception(self, client, mocker):
        mock_album = mocker.MagicMock()
        mock_album.albumartist = "Artist"
        mock_album.album = "Album"
        mock_album.get.return_value = "Rock"
        mock_lib = mocker.MagicMock()
        mock_lib.get_album.return_value = mock_album
        mocker.patch("src.routes.genres._init_beets", return_value=mock_lib)

        mock_plugin = mocker.MagicMock()
        mock_plugin.name = "lastgenre"
        mock_plugin._process.side_effect = RuntimeError("plugin error")
        mocker.patch("beets.plugins.find_plugins", return_value=[mock_plugin])

        resp = client.post("/api/album/1/genre")
        assert resp.status_code == 500
        # Verify pretend was reset (False) even after error
        mock_plugin.config.__getitem__.return_value.set.assert_called_with(False)


# ---------------------------------------------------------------------------
# POST /api/album/<id>/genre/confirm
# ---------------------------------------------------------------------------


class TestConfirmGenre:
    def test_returns_404_when_album_not_found(self, client, mocker):
        mock_lib = mocker.MagicMock()
        mock_lib.get_album.return_value = None
        mocker.patch("src.routes.genres._init_beets", return_value=mock_lib)
        resp = client.post("/api/album/9999/genre/confirm")
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "Album not found"

    def test_returns_500_when_lastgenre_plugin_not_loaded(self, client, mocker):
        mock_album = mocker.MagicMock()
        mock_lib = mocker.MagicMock()
        mock_lib.get_album.return_value = mock_album
        mocker.patch("src.routes.genres._init_beets", return_value=mock_lib)
        mocker.patch("beets.plugins.find_plugins", return_value=[])
        resp = client.post("/api/album/1/genre/confirm")
        assert resp.status_code == 500
        assert resp.get_json()["error"] == "lastgenre plugin not loaded"

    def test_calls_process_with_write_true(self, client, mocker):
        mock_album = mocker.MagicMock()
        mock_album.albumartist = "Artist"
        mock_album.album = "Album"
        mock_album.get.return_value = "Jazz"
        mock_lib = mocker.MagicMock()
        mock_lib.get_album.return_value = mock_album
        mocker.patch("src.routes.genres._init_beets", return_value=mock_lib)

        mock_plugin = mocker.MagicMock()
        mock_plugin.name = "lastgenre"
        mocker.patch("beets.plugins.find_plugins", return_value=[mock_plugin])

        resp = client.post("/api/album/1/genre/confirm")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "genre" in data
        mock_plugin._process.assert_called_once_with(mock_album, write=True)

    def test_returns_formatted_genre(self, client, mocker):
        mock_album = mocker.MagicMock()
        mock_album.albumartist = "Artist"
        mock_album.album = "Album"
        mock_album.get.return_value = ["Rock", "Pop"]
        mock_lib = mocker.MagicMock()
        mock_lib.get_album.return_value = mock_album
        mocker.patch("src.routes.genres._init_beets", return_value=mock_lib)

        mock_plugin = mocker.MagicMock()
        mock_plugin.name = "lastgenre"
        mocker.patch("beets.plugins.find_plugins", return_value=[mock_plugin])

        resp = client.post("/api/album/1/genre/confirm")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["genre"] == "Rock, Pop"


# ---------------------------------------------------------------------------
# POST /api/album/<id>/genre/save
# ---------------------------------------------------------------------------


class TestSaveGenre:
    def test_returns_400_when_genre_is_empty(self, client):
        resp = client.post(
            "/api/album/1/genre/save",
            json={"genre": ""},
        )
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Genre cannot be empty"

    def test_returns_400_when_no_body(self, client):
        resp = client.post("/api/album/1/genre/save", json={})
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Genre cannot be empty"

    def test_returns_404_when_album_not_found(self, client, mocker):
        mock_lib = mocker.MagicMock()
        mock_lib.get_album.return_value = None
        mocker.patch("src.routes.genres._init_beets", return_value=mock_lib)
        resp = client.post("/api/album/9999/genre/save", json={"genre": "Rock"})
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "Album not found"

    def test_saves_single_genre_to_album_and_items(self, client, mocker):
        mock_item = mocker.MagicMock()
        mock_album = mocker.MagicMock()
        mock_album.items.return_value = [mock_item]
        mock_lib = mocker.MagicMock()
        mock_lib.get_album.return_value = mock_album
        mocker.patch("src.routes.genres._init_beets", return_value=mock_lib)

        resp = client.post("/api/album/1/genre/save", json={"genre": "Jazz"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["genre"] == "Jazz"

        assert mock_album.genre == "Jazz"
        assert mock_album.store.called
        assert mock_item.genre == "Jazz"
        assert mock_item.store.called
        assert mock_item.try_write.called

    def test_saves_multiple_genres_as_list(self, client, mocker):
        mock_item = mocker.MagicMock()
        mock_album = mocker.MagicMock()
        # Ensure hasattr(album, "genres") returns True
        type(mock_album).genres = mocker.PropertyMock(return_value=[])
        mock_album.items.return_value = [mock_item]
        type(mock_item).genres = mocker.PropertyMock(return_value=[])
        mock_lib = mocker.MagicMock()
        mock_lib.get_album.return_value = mock_album
        mocker.patch("src.routes.genres._init_beets", return_value=mock_lib)

        resp = client.post(
            "/api/album/1/genre/save", json={"genre": "Rock, Pop, Electronic"}
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["genre"] == "Rock, Pop, Electronic"
        # genre (singular) should be set to the first value
        assert mock_album.genre == "Rock"

    def test_strips_whitespace_from_genre(self, client, mocker):
        mock_album = mocker.MagicMock()
        mock_album.items.return_value = []
        mock_lib = mocker.MagicMock()
        mock_lib.get_album.return_value = mock_album
        mocker.patch("src.routes.genres._init_beets", return_value=mock_lib)

        resp = client.post(
            "/api/album/1/genre/save", json={"genre": "  Rock  "}
        )
        assert resp.status_code == 200
        assert resp.get_json()["genre"] == "Rock"
