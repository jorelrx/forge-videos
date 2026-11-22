import { BoardCriativo } from "../../../../components/board-criativo";

export default async function BoardPage({params}: {params: Promise<{canal: string}>}) {
  return <BoardCriativo canal={(await params).canal}/>;
}
