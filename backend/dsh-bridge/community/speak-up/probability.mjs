// Derived from dsh-speak-up by Yuuyuko-uu. See LICENSE and upstream.json.
export function 算命中线(基础命中线, 因子, 连没中, 没中加成, 加成上限) {
  const 加成 = Math.min(加成上限, 连没中 * 没中加成)
  const 线 = Math.min(100, Math.max(0, 基础命中线 * 因子 + 加成))
  return { 加成, 线 }
}
