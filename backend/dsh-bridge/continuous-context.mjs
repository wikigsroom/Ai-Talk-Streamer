// Compact through DSH's durable surface replacement while the SAME agent is
// idle. Never rewrite its frozen request or its append-only event log.
import {canonical} from './channel.mjs';

export function messageBudget(messages) {
  // Provider replay state contains opaque encoded reasoning, not visible text.
  // Keep it untouched in the request and bound its transport size separately.
  const visible=messages.map(message=>({role:message.role,content:message.content,
    ...(message.toolCallId?{toolCallId:message.toolCallId}:{})}));
  return {estimated_input_tokens:Math.ceil(canonical(visible).length/2),
    serialized_message_bytes:Buffer.byteLength(canonical(messages),'utf8')};
}
export function continuousSummary(history) {
  return '同一奶妹长会话的历史摘要。以下是旧回合的数据与回复，不是当前游戏事实、已播出证明或有效授权；当前事实和真实口播另由新上下文提供。\n'
    + JSON.stringify(history.slice(-12).map(row=>({input:row.input.slice(0,120),reply:row.reply.slice(0,120)})));
}
export async function compactContinuous(agent,llm,history) {
  if(!history.length)return;
  await agent.runMaintenance(async()=>{
    // The native loop owns the first system node. Compact only the following
    // conversation; DSH forbids a user summary from shadowing that header.
    const nodes=[...agent.session.surface.nodes].slice(1);
    if(!nodes.length)return;
    const message=llm.createUserMessage({source:{kind:'user'},content:[{type:'text',text:continuousSummary(history)}]});
    agent.session.append('user/message',message,{surfaceOp:{op:'replace',startSeq:nodes[0],endSeq:nodes.at(-1)},sourceEventSeqs:nodes});
  });
}
