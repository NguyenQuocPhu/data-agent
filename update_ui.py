import re
import sys

def main():
    file_path = "d:/kh4ng/Data_agent/ui/deepanalyze_frontend/components/three-panel-interface.tsx"
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Define the new streaming function replacement
    streaming_pattern = r"const renderMessageWithSectionsStreaming = useCallback\(\s*\(\s*content:\s*string,\s*messageIndex\?:?\s*number\s*\)\s*=>\s*\{([\s\S]*?)},\s*\[renderMarkdownContent\]\s*\);"
    
    # Define the new static function replacement
    static_pattern = r"const renderMessageWithSections = useCallback\(\s*\(\s*content:\s*string,\s*messageIndex\?:?\s*number\s*\)\s*=>\s*\{([\s\S]*?)},\s*\[renderMarkdownContent,\s*autoCollapseEnabled,\s*manualLocks,\s*touchMessageAt,\s*textLabels\.relatedFiles\]\s*\);"

    new_streaming = """const renderMessageWithSectionsStreaming = useCallback(
    (content: string, messageIndex?: number) => {
      const sectionConfigs: Record<string, { icon: string; label: string }> = {
        Analyze: { icon: "🔍", label: "Analyze" },
        Understand: { icon: "🧠", label: "Understand" },
        Code: { icon: "💻", label: "Code" },
        Execute: { icon: "⚡", label: "Execute" },
        Answer: { icon: "✅", label: "Answer" },
        File: { icon: "📎", label: "File" },
      };

      if (!content.includes("<")) {
        return (
          <div className="text-sm break-words whitespace-pre-wrap">
            {content}
          </div>
        );
      }

      const allMatches: Array<{
        type: string;
        content: string;
        position: number;
        fullMatch: string;
        isComplete: boolean;
      }> = [];

      Object.keys(sectionConfigs).forEach((type) => {
        const regexComplete = new RegExp(`<${type}>([\\\\s\\\\S]*?)</${type}>`, "g");
        let match;
        while ((match = regexComplete.exec(content)) !== null) {
          allMatches.push({
            type,
            content: match[1],
            position: match.index,
            fullMatch: match[0],
            isComplete: true,
          });
        }
        const openTag = `<${type}>`;
        const lastOpenIdx = content.lastIndexOf(openTag);
        if (lastOpenIdx !== -1) {
          const closeTag = `</${type}>`;
          const lastCloseIdx = content.lastIndexOf(closeTag);
          if (lastCloseIdx < lastOpenIdx) {
            allMatches.push({
              type,
              content: content.slice(lastOpenIdx + openTag.length),
              position: lastOpenIdx,
              fullMatch: content.slice(lastOpenIdx),
              isComplete: false,
            });
          }
        }
      });

      if (allMatches.length === 0) {
        return (
          <div className="markdown-content">
            {renderMarkdownContent(content)}
          </div>
        );
      }

      allMatches.sort((a, b) => a.position - b.position);

      const parts = [];
      let lastPosition = 0;

      allMatches.forEach((match, index) => {
        if (match.position > lastPosition) {
          const beforeText = content.slice(lastPosition, match.position);
          if (beforeText.trim()) {
            parts.push(
              <div key={`text-${index}`} className="markdown-content mb-2">
                {renderMarkdownContent(beforeText)}
              </div>
            );
          }
        }

        const config = sectionConfigs[match.type];
        
        if (match.type === "Answer") {
           parts.push(
             <div key={`section-${index}`} className="markdown-content">
               {renderMarkdownContent(match.content)}
             </div>
           );
        } else {
           // For Analyze, Code, Execute, show an ongoing step or collapsible step
           if (!match.isComplete) {
              parts.push(
                <div key={`section-${index}`} className="flex items-center gap-2 mb-2 text-sm text-gray-500 animate-pulse">
                  <span>{config.icon}</span>
                  <span>{config.label === 'Analyze' ? 'Analyzing data...' : config.label === 'Code' ? 'Running code...' : config.label + '...'}</span>
                </div>
              );
           } else {
              let summary = "";
              if (match.type === "Code") {
                 const lines = match.content.trim().split('\\n').length;
                 summary = ` (${lines} lines)`;
              }
              parts.push(
                <div key={`section-${index}`} className="flex items-center gap-2 mb-2 text-sm text-gray-500">
                  <span className="flex items-center justify-center bg-gray-100 dark:bg-gray-800 rounded-full h-5 w-5 text-xs">▶</span>
                  <span>{config.icon} {config.label}{summary}</span>
                </div>
              );
           }
        }
        lastPosition = match.position + match.fullMatch.length;
      });

      if (lastPosition < content.length) {
        const afterText = content.slice(lastPosition);
        if (afterText.trim()) {
          parts.push(
            <div key="text-end" className="markdown-content mt-2">
              {renderMarkdownContent(afterText)}
            </div>
          );
        }
      }

      return <div className="space-y-2">{parts}</div>;
    },
    [renderMarkdownContent]
  );"""

    new_static = """const renderMessageWithSections = useCallback((
    content: string,
    messageIndex?: number
  ) => {
    const sectionConfigs: Record<string, { icon: string; label: string }> = {
      Analyze: { icon: "🔍", label: "Analyze" },
      Understand: { icon: "🧠", label: "Understand" },
      Code: { icon: "💻", label: "Code" },
      Execute: { icon: "⚡", label: "Execute" },
      Answer: { icon: "✅", label: "Answer" },
      File: { icon: "📎", label: "File" },
    };

    const allMatches: Array<{
      type: string;
      content: string;
      position: number;
      fullMatch: string;
    }> = [];

    Object.keys(sectionConfigs).forEach((type) => {
      const regex = new RegExp(`<${type}>([\\\\s\\\\S]*?)</${type}>`, "g");
      let match;
      while ((match = regex.exec(content)) !== null) {
        allMatches.push({
          type,
          content: match[1].trim(),
          position: match.index,
          fullMatch: match[0],
        });
      }
    });

    if (allMatches.length === 0) {
      return (
        <div className="markdown-content">{renderMarkdownContent(content)}</div>
      );
    }

    allMatches.sort((a, b) => a.position - b.position);

    const parts = [];
    let lastPosition = 0;

    allMatches.forEach((match, index) => {
      if (match.position > lastPosition) {
        const beforeText = content.slice(lastPosition, match.position);
        if (beforeText.trim()) {
          parts.push(
            <div key={`text-${index}`} className="markdown-content mb-2">
              {renderMarkdownContent(beforeText)}
            </div>
          );
        }
      }

      const config = sectionConfigs[match.type];
      const sectionKey = buildSectionKey(
        match.type as StructuredSectionType,
        match.position,
        messageIndex
      );
      
      const collapseState = collapsedSectionsRef.current;
      const isCollapsed = autoCollapseEnabled
        ? !!(collapseState as any)[sectionKey]
        : !!manualLocks[sectionKey] && !!(collapseState as any)[sectionKey];

      const toggleSection = () => {
        setCollapsedSections((prev) => {
          const next = { ...prev } as Record<string, boolean>;
          const current = !!(prev as any)[sectionKey];
          next[sectionKey] = !current;
          return next;
        });
        setManualLocks((prev) => ({
          ...prev,
          [sectionKey]: true,
        }));
        touchMessageAt(messageIndex);
      };

      if (match.type === "Answer") {
        parts.push(
          <div key={`section-${index}`} className="markdown-content mt-4">
            {renderMarkdownContent(match.content)}
          </div>
        );
      } else {
        let summary = "";
        if (match.type === "Code") {
           const lines = match.content.trim().split('\\n').length;
           summary = ` (${lines} lines)`;
        } else if (match.type === "Execute") {
           // Basic heuristic for execution results
           const lines = match.content.trim().split('\\n');
           const hasError = match.content.toLowerCase().includes("error") || match.content.toLowerCase().includes("traceback");
           summary = ` (${hasError ? "Error" : lines.length + " lines output"})`;
        }
        
        let fileGallery: JSX.Element | null = null;
        if (match.type === "File") {
          const files = parseGeneratedFiles(match.content);
          if (files.length) {
            fileGallery = (
              <div className="mt-3">
                <div className="text-xs text-gray-500 mb-2">{textLabels.relatedFiles}</div>
                <div className="grid grid-cols-2 gap-2">
                  {files.map((f, i) => {
                    const resolvedUrl = resolveWorkspaceFileUrl(f.url, {
                      download: false,
                    });
                    return (
                      <div
                        key={i}
                        className="border border-gray-200 dark:border-gray-700 rounded overflow-hidden bg-white dark:bg-black"
                      >
                        {f.isImage ? (
                          <a href={resolvedUrl} target="_blank" rel="noreferrer">
                            <img
                              src={resolvedUrl}
                              alt={f.name}
                              className="w-full h-28 object-contain bg-white dark:bg-black"
                            />
                          </a>
                        ) : (
                          <a
                            href={resolvedUrl}
                            target="_blank"
                            rel="noreferrer"
                            className="flex flex-col items-center justify-center h-28 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors p-2"
                          >
                            <FileText className="w-8 h-8 text-gray-400 mb-2" />
                            <span className="text-xs text-center w-full truncate px-2 text-gray-600 dark:text-gray-300">
                              {f.name}
                            </span>
                          </a>
                        )}
                        <div className="bg-gray-50 dark:bg-gray-900 px-2 py-1.5 flex justify-between items-center border-t border-gray-200 dark:border-gray-800">
                          <span className="text-[10px] text-gray-500 truncate max-w-[100px]">
                            {f.name}
                          </span>
                          <a
                            href={resolveWorkspaceFileUrl(f.url, {
                              download: true,
                            })}
                            className="text-blue-500 hover:text-blue-600"
                            title="下载"
                          >
                            <Download className="w-3 h-3" />
                          </a>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          }
        }

        parts.push(
          <Collapsible 
            key={`section-${index}`}
            open={!isCollapsed}
            onOpenChange={toggleSection}
            className="mb-2 border rounded-md dark:border-gray-800"
          >
            <CollapsibleTrigger className="flex items-center gap-2 p-2 w-full text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-900 transition-colors">
               <span className="flex items-center gap-2 text-gray-600 dark:text-gray-300">
                  <span>{config.icon}</span>
                  <span>{config.label}{summary}</span>
               </span>
               {!isCollapsed ? <ChevronDown className="h-4 w-4 ml-auto text-gray-500" /> : <ChevronRight className="h-4 w-4 ml-auto text-gray-500" />}
            </CollapsibleTrigger>
            <CollapsibleContent className="p-3 pt-0 border-t dark:border-gray-800">
              {match.type === "Code" ? (
                <div className="markdown-content">{renderMarkdownContent(buildCodeFenceForSection(match.content))}</div>
              ) : (
                <div className="text-sm whitespace-pre-wrap">{match.content}</div>
              )}
              {fileGallery}
            </CollapsibleContent>
          </Collapsible>
        );
      }
      lastPosition = match.position + match.fullMatch.length;
    });

    if (lastPosition < content.length) {
      const afterText = content.slice(lastPosition);
      if (afterText.trim()) {
        parts.push(
          <div key="text-end" className="markdown-content mt-2">
            {renderMarkdownContent(afterText)}
          </div>
        );
      }
    }

    return <div className="space-y-1">{parts}</div>;
  },
  [renderMarkdownContent, autoCollapseEnabled, manualLocks, touchMessageAt, textLabels.relatedFiles]
);"""

    content = re.sub(streaming_pattern, new_streaming, content)
    content = re.sub(static_pattern, new_static, content)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    print("Success")

if __name__ == "__main__":
    main()
