import { useState } from "react";
import { ChatDataRow } from "../../api/chat";

type ChatBubbleProps = {
	role: "user" | "assistant";
	text: string;
	data?: ChatDataRow[] | null;
};

export default function ChatBubble({ role, text, data }: ChatBubbleProps) {
	const [expanded, setExpanded] = useState(false);
	const columns = data?.[0] ? Object.keys(data[0]) : [];

	return (
		<div className={`chat-bubble-row ${role}`}>
			<div className={`chat-bubble ${role}`}>
				<p>{text}</p>

				{data && data.length > 0 && (
					<div className="chat-data">
						<button type="button" onClick={() => setExpanded((current) => !current)}>
							{expanded ? "Hide query result" : `Show query result (${data.length} rows)`}
						</button>

						{expanded && (
							<div className="table-wrap">
								<table>
									<thead>
										<tr>
											{columns.map((column) => (
												<th key={column}>{column}</th>
											))}
										</tr>
									</thead>

									<tbody>
										{data.map((row, rowIndex) => (
											<tr key={rowIndex}>
												{columns.map((column) => (
													<td key={column}>{String(row[column] ?? "")}</td>
												))}
											</tr>
										))}
									</tbody>
								</table>
							</div>
						)}
					</div>
				)}
			</div>
		</div>
	);
}
