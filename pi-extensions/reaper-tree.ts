/**
 * Reaper tree extension — fills the gaps that pi's RPC surface does not expose.
 *
 * Why this exists: the RPC protocol has `get_tree`, `fork` and `clone`, but no
 * `navigate_tree`. The TUI's `/tree` navigation (and branch summarization) is
 * only reachable from `ExtensionCommandContext`. Extension commands, however,
 * *are* invokable over RPC via the `prompt` command, so this file bridges the
 * two: Reaper sends `/goto <entryId>` as a prompt and the navigation happens
 * inside the same pi process, with the same session state.
 *
 * Loaded with `pi --extension <path>` (see src/chat/session.py). Commands are
 * discoverable at runtime via the RPC `get_commands` call.
 *
 * Results are reported with ctx.ui.notify(), which in RPC mode arrives on
 * stdout as an `extension_ui_request` with method "notify" — the panel shows
 * those as system lines.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

/** First whitespace-delimited token. */
function firstToken(args: string): string {
	return (args || "").trim().split(/\s+/)[0] || "";
}

/**
 * Structural (tree-mutating) operations must not run while the agent is mid-run.
 *
 * pi issue #5096: navigating the tree during tool execution appends tool results
 * with the wrong `parentId`, corrupting the session — the result lands on the
 * branch you moved to, and the provider then rejects the conversation with
 * "unexpected tool_use_id found in tool_result blocks". Maintainer guidance was
 * explicit: *"we should disallow structural operations, i.e. operations that
 * operate on the tree, during streaming"* — the same rule already applies to
 * /reload. `ctx.isIdle()` is false while a run, a retry, or a retry of
 * auto-compaction is pending.
 */
function requireIdle(ctx: any): boolean {
	if (typeof ctx.isIdle !== "function" || ctx.isIdle()) return true;
	ctx.ui.notify(
		"agent 正在运行中：请先等它结束或点停止。运行中做结构性操作会破坏会话树（pi issue #5096）。",
		"warning",
	);
	return false;
}

export default function (pi: ExtensionAPI) {
	// Move the active branch to an existing entry. This is the TUI's `/tree`
	// navigation, which has no RPC command.
	pi.registerCommand("goto", {
		description:
			"Move the active branch to a session entry (usage: /goto <entryId> [summary])",
		handler: async (args, ctx) => {
			const entryId = firstToken(args);
			if (!entryId) {
				ctx.ui.notify("usage: /goto <entryId> [summary]", "warning");
				return;
			}
			if (!requireIdle(ctx)) return;
			const summarize = /\bsummary\b/i.test(args);

			// Make sure the entry actually exists before moving — a bad id would
			// otherwise fail deep inside the session manager.
			const entries = ctx.sessionManager.getEntries();
			if (!entries.some((e) => e.id === entryId)) {
				ctx.ui.notify(`entry not found: ${entryId}`, "error");
				return;
			}

			try {
				const result = await ctx.navigateTree(entryId, { summarize });
				if (result?.cancelled) {
					ctx.ui.notify("navigation cancelled", "warning");
				} else {
					ctx.ui.notify(
						summarize
							? `moved to ${entryId} (branch summarized)`
							: `moved to ${entryId}`,
						"info",
					);
				}
			} catch (e) {
				ctx.ui.notify(`navigateTree failed: ${String(e)}`, "error");
			}
		},
	});

	// Labels are what make a long tree navigable: they are rendered as chips in
	// the panel's tree view and in pi's own /tree selector.
	pi.registerCommand("label", {
		description:
			"Label an entry (usage: /label <entryId> <text>; or /label <text> for the last assistant message)",
		handler: async (args, ctx) => {
			const trimmed = (args || "").trim();
			if (!trimmed) {
				ctx.ui.notify("usage: /label <entryId> <text> | /label <text>", "warning");
				return;
			}
			if (!requireIdle(ctx)) return;

			const entries = ctx.sessionManager.getEntries();
			const tokens = trimmed.split(/\s+/);
			const head = tokens[0];

			// Two forms: an explicit entry id, or a label for the newest
			// assistant message (the common case from the UI).
			if (entries.some((e) => e.id === head) && tokens.length > 1) {
				pi.setLabel(head, tokens.slice(1).join(" "));
				ctx.ui.notify(`labeled ${head}`, "info");
				return;
			}

			for (let i = entries.length - 1; i >= 0; i--) {
				const e = entries[i];
				if (e.type === "message" && e.message.role === "assistant") {
					pi.setLabel(e.id, trimmed);
					ctx.ui.notify(`labeled ${e.id}`, "info");
					return;
				}
			}
			ctx.ui.notify("no assistant message to label", "warning");
		},
	});

	pi.registerCommand("unlabel", {
		description: "Remove the label from an entry (usage: /unlabel <entryId>)",
		handler: async (args, ctx) => {
			const entryId = firstToken(args);
			if (!entryId) {
				ctx.ui.notify("usage: /unlabel <entryId>", "warning");
				return;
			}
			pi.setLabel(entryId, undefined);
			ctx.ui.notify(`unlabeled ${entryId}`, "info");
		},
	});

	// Cheap introspection for the panel's status bar and for debugging.
	pi.registerCommand("where", {
		description: "Report the current leaf entry id",
		handler: async (_args, ctx) => {
			const entries = ctx.sessionManager.getEntries();
			const leaf = entries.length ? entries[entries.length - 1].id : "(empty)";
			ctx.ui.notify(`leaf: ${leaf}`, "info");
		},
	});
}
