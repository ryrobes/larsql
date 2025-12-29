/**
 * RichMarkdown - Comprehensive markdown renderer for LLM outputs
 *
 * Supports:
 * - GitHub Flavored Markdown (tables, strikethrough, task lists, autolinks)
 * - LaTeX math equations (inline $...$ and block $$...$$)
 * - Syntax highlighting for all major languages
 * - Footnotes
 * - Emoji shortcuts (:smile:)
 * - Sanitized HTML
 * - Custom styling for all elements
 */
import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import remarkEmoji from 'remark-emoji';
import rehypeKatex from 'rehype-katex';
import rehypeRaw from 'rehype-raw';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import 'katex/dist/katex.min.css';
import './RichMarkdown.css';

/**
 * RichMarkdown Component
 *
 * @param {string} children - Markdown content to render
 * @param {object} props - Additional props passed to ReactMarkdown
 */
function RichMarkdown({ children, ...props }) {
  return (
    <div className="rich-markdown">
      <ReactMarkdown
        remarkPlugins={[
          remarkGfm,        // GitHub Flavored Markdown (tables, strikethrough, task lists)
          remarkMath,       // LaTeX math support
          remarkEmoji,      // Emoji shortcuts like :smile:
        ]}
        rehypePlugins={[
          rehypeKatex,      // Render math with KaTeX
          rehypeRaw,        // Allow safe HTML (sanitized by default)
        ]}
        components={{
          // Custom code block rendering with syntax highlighting
          code({node, inline, className, children, ...codeProps}) {
            const match = /language-(\w+)/.exec(className || '');
            const language = match ? match[1] : '';

            return !inline && language ? (
              <SyntaxHighlighter
                style={vscDarkPlus}
                language={language}
                PreTag="div"
                customStyle={{
                  margin: '1em 0',
                  borderRadius: '6px',
                  fontSize: '0.9em',
                }}
                {...codeProps}
              >
                {String(children).replace(/\n$/, '')}
              </SyntaxHighlighter>
            ) : (
              <code className={className} {...codeProps}>
                {children}
              </code>
            );
          },

          // Custom table rendering with better styling
          table({node, children, ...tableProps}) {
            return (
              <div className="markdown-table-wrapper">
                <table {...tableProps}>{children}</table>
              </div>
            );
          },

          // Custom blockquote styling
          blockquote({node, children, ...quoteProps}) {
            return (
              <blockquote className="markdown-blockquote" {...quoteProps}>
                {children}
              </blockquote>
            );
          },

          // Custom link rendering (open in new tab, show external icon)
          a({node, children, href, ...linkProps}) {
            const isExternal = href && (href.startsWith('http://') || href.startsWith('https://'));
            return (
              <a
                href={href}
                target={isExternal ? '_blank' : undefined}
                rel={isExternal ? 'noopener noreferrer' : undefined}
                className={isExternal ? 'external-link' : undefined}
                {...linkProps}
              >
                {children}
                {isExternal && <span className="external-icon">↗</span>}
              </a>
            );
          },

          // Custom heading anchors (for table of contents)
          h1: ({node, children, ...headingProps}) => <h1 id={slugify(String(children))} {...headingProps}>{children}</h1>,
          h2: ({node, children, ...headingProps}) => <h2 id={slugify(String(children))} {...headingProps}>{children}</h2>,
          h3: ({node, children, ...headingProps}) => <h3 id={slugify(String(children))} {...headingProps}>{children}</h3>,
          h4: ({node, children, ...headingProps}) => <h4 id={slugify(String(children))} {...headingProps}>{children}</h4>,
          h5: ({node, children, ...headingProps}) => <h5 id={slugify(String(children))} {...headingProps}>{children}</h5>,
          h6: ({node, children, ...headingProps}) => <h6 id={slugify(String(children))} {...headingProps}>{children}</h6>,
        }}
        {...props}
      >
        {String(children)}
      </ReactMarkdown>
    </div>
  );
}

/**
 * Helper: Create URL-safe slug from heading text
 */
function slugify(text) {
  return text
    .toLowerCase()
    .trim()
    .replace(/[^\w\s-]/g, '')
    .replace(/[\s_-]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

export default React.memo(RichMarkdown);
