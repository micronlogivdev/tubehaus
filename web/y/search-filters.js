// Local search refinements. Upstream search still supplies the candidate videos.
export const LOCAL_SORTS = new Set(["views_asc", "date_asc"]);

export function viewLimit(value) {
  if (value == null || !/^\d+$/.test(String(value))) return "";
  const n = Number(value);
  return Number.isSafeInteger(n) && n >= 0 ? String(n) : "";
}

function count(value) {
  return value == null || value === "" || !Number.isFinite(Number(value)) || Number(value) < 0 ? null : Number(value);
}

export function refineSearch(items, { sort, min_views = "", max_views = "" }) {
  const ranged = min_views !== "" || max_views !== "";
  const videosOnly = ranged || LOCAL_SORTS.has(sort);
  let result = items.filter((x) => {
    if (videosOnly && !(x.type === "video" || x.type === "shortVideo" || x.videoId)) return false;
    if (!ranged) return true;
    const views = count(x.viewCount);
    return views !== null && (min_views === "" || views >= Number(min_views)) && (max_views === "" || views <= Number(max_views));
  });
  if (LOCAL_SORTS.has(sort)) {
    const key = sort === "views_asc" ? "viewCount" : "published";
    result.sort((a, b) => {
      const av = count(a[key]), bv = count(b[key]);
      // Missing/zero upload dates are unknown, never the earliest upload.
      const aa = key === "published" && av === 0 ? null : av;
      const bb = key === "published" && bv === 0 ? null : bv;
      return aa === null ? (bb === null ? 0 : 1) : bb === null ? -1 : aa - bb;
    });
  }
  return result;
}

export function searchSourceSort(sort) {
  // Reversing a "most viewed" page would not discover low-view candidates.
  return LOCAL_SORTS.has(sort) ? "relevance" : sort;
}
