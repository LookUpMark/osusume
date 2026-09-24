"""Le 6 query GraphQL di ``src/server/anilist.ts`` — COPIATE verbatim.

Le stringhe sono parte della cache key (``sha256(query + JSON.stringify(variables))``)
condivisa col backend TS: una virgola di differenza invalida in silenzio la cache
su disco. Costruite per concatenazione (non f-string) per non toccare le graffe
GraphQL e mantenere i byte identici al template literal TS.
"""

from __future__ import annotations

MEDIA_FIELDS = """
  id
  title { romaji }
  format
  seasonYear
  genres
  tags { name rank isGeneralSpoiler isMediaSpoiler }
  averageScore
  popularity
  coverImage { large color }
  studios(isMain: true) { nodes { name } }
  siteUrl
  description(asHtml: false)
"""

LIST_LIST_QUERY = (
    """
query ($userName: String, $chunk: Int, $type: MediaType) {
  MediaListCollection(userName: $userName, type: $type, chunk: $chunk, perChunk: 500) {
    hasNextChunk
    lists {
      isCustomList
      entries {
        status
        score(format: POINT_100)
        repeat
        updatedAt
        media { """
    + MEDIA_FIELDS
    + """ }
      }
    }
  }
}"""
)

MEDIA_PAGE_QUERY = (
    """
query ($page: Int, $genre_in: [String], $tag_in: [String], $sort: [MediaSort], $minimumTagRank: Int, $type: MediaType) {
  Page(page: $page, perPage: 50) {
    pageInfo { hasNextPage }
    media(type: $type, isAdult: false, genre_in: $genre_in, tag_in: $tag_in, sort: $sort, minimumTagRank: $minimumTagRank) {
      """
    + MEDIA_FIELDS
    + """
      relations { edges { relationType node { id } } }
    }
  }
}"""
)

MEDIA_BY_IDS_QUERY = (
    """
query ($id_in: [Int], $type: MediaType) {
  Page(perPage: 50) {
    media(id_in: $id_in, type: $type) { """
    + MEDIA_FIELDS
    + """ relations { edges { relationType node { id } } } }
  }
}"""
)

MEDIA_SEARCH_QUERY = (
    """
query ($q: String, $type: MediaType) {
  Page(perPage: 6) {
    media(search: $q, type: $type, isAdult: false, sort: SEARCH_MATCH) {
      """
    + MEDIA_FIELDS
    + """ relations { edges { relationType node { id } } }
    }
  }
}"""
)

RECOMMENDATIONS_QUERY = """
query ($id: Int) {
  Media(id: $id) {
    recommendations(sort: RATING_DESC, perPage: 10) {
      nodes { rating mediaRecommendation { id } }
    }
  }
}"""

MEDIA_REVIEWS_QUERY = """
query ($id: Int) {
  Media(id: $id) {
    reviews(sort: RATING_DESC, perPage: 3) {
      nodes { summary body(asHtml: false) score rating }
    }
  }
}"""

VIEWER_QUERY = """
query {
  Viewer { name }
}"""

SAVE_PLANNING_MUTATION = """
mutation ($mediaId: Int) {
  SaveMediaListEntry(mediaId: $mediaId, status: PLANNING) { id status }
}"""

MEDIA_LIST_STATUS_QUERY = """
query ($userName: String, $mediaId: Int) {
  MediaList(userName: $userName, mediaId: $mediaId) { status }
}"""
