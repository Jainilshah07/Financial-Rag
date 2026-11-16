// Citations in an answer, e.g. "(po-1.pdf, Page 2)", "Pages 1-2", "Pages 1, 3", as a Set of "file#page".
// Matching file and page (not page alone) keeps "Page 1" of one document from marking every page 1.
const CITATION = /([\w.-]+\.pdf),\s*Pages?\s*(\d+(?:\s*(?:-|–|,|and)\s*\d+)*)/gi

export function citedPages(answer) {
  const text = answer.replace(/[‐-‒−]/g, '-') // the model sometimes writes non-breaking hyphens
  const cited = new Set()
  for (const [, file, pages] of text.matchAll(CITATION)) {
    const nums = pages.match(/\d+/g).map(Number)
    const list = /[-–]/.test(pages) && nums.length === 2
      ? Array.from({ length: nums[1] - nums[0] + 1 }, (_, i) => nums[0] + i)
      : nums
    list.forEach((page) => cited.add(`${file}#${page}`))
  }
  return cited
}
