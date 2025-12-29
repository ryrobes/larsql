import React, { useState, useEffect, useCallback } from 'react';
import RichMarkdown from './RichMarkdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import './DynamicUI.css';

// Import new section components
import ImageSection from './sections/ImageSection';
import DataTableSection from './sections/DataTableSection';
import CodeSection from './sections/CodeSection';
import CardGridSection from './sections/CardGridSection';
import ComparisonSection from './sections/ComparisonSection';
import AccordionSection from './sections/AccordionSection';
import TabsSection from './sections/TabsSection';
import HTMLSection from './sections/HTMLSection';

// Import layout components
import TwoColumnLayout from './layouts/TwoColumnLayout';
import GridLayout from './layouts/GridLayout';
import SidebarLayout from './layouts/SidebarLayout';

/**
 * DynamicUI - Renders UI specifications from backend checkpoints
 *
 * Supports all built-in UI section types:
 * - preview: Display content (text, markdown, code)
 * - header: Display heading with optional icon
 * - text: Free text input OR static text display (auto-detected)
 * - text_input: Free text input field
 * - confirmation: Yes/No buttons
 * - choice: Radio buttons (single select)
 * - multi_choice: Checkboxes (multi select)
 * - rating: Star rating
 * - slider: Range slider
 * - form: Multiple fields
 *
 * NEW Generative UI section types:
 * - image: Display images with lightbox
 * - data_table: Display tabular data
 * - code: Syntax highlighted code with diff support
 * - card_grid: Rich option cards
 * - comparison: Side-by-side comparison
 * - accordion: Collapsible panels
 * - tabs: Tabbed content
 * - html: Raw HTML with HTMX support (SECURITY WARNING: No sanitization)
 *
 * NEW Layout types:
 * - vertical: Stack sections (default)
 * - two-column: Two column layout
 * - three-column: Three column layout
 * - grid: CSS grid layout
 * - sidebar-left: Sidebar on left
 * - sidebar-right: Sidebar on right
 */
function DynamicUI({ spec, onSubmit, isLoading, phaseOutput, checkpointId, sessionId }) {
  const [values, setValues] = useState({});
  const [errors, setErrors] = useState({});

  // Initialize values from spec defaults
  useEffect(() => {
    const initialValues = {};
    const collectDefaults = (sections) => {
      (sections || []).forEach((section, idx) => {
        const key = section.input_name || section.label || section.prompt || `section_${idx}`;
        if (section.default !== undefined) {
          initialValues[key] = section.default;
        }
        // Handle nested sections in tabs
        if (section.tabs) {
          section.tabs.forEach(tab => collectDefaults(tab.sections));
        }
        // Handle nested sections in groups
        if (section.sections) {
          collectDefaults(section.sections);
        }
      });
    };

    // Collect from main sections
    collectDefaults(spec?.sections);

    // Collect from column sections
    (spec?.columns || []).forEach(col => collectDefaults(col.sections));

    setValues(initialValues);
  }, [spec]);

  const handleChange = useCallback((key, value) => {
    setValues(prev => ({ ...prev, [key]: value }));
    setErrors(prev => ({ ...prev, [key]: null }));
  }, []);

  const handleSubmit = (e) => {
    e?.preventDefault();

    // Validate required fields
    const newErrors = {};
    const validateSections = (sections) => {
      (sections || []).forEach((section, idx) => {
        const key = section.input_name || section.label || section.prompt || `section_${idx}`;
        if (section.required && !values[key]) {
          newErrors[key] = 'Required';
        }
      });
    };

    validateSections(spec?.sections);
    (spec?.columns || []).forEach(col => validateSections(col.sections));

    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }

    onSubmit(values);
  };

  // Evaluate show_if condition
  const evaluateCondition = useCallback((condition) => {
    if (!condition) return true;

    const fieldValue = values[condition.field];

    if (condition.equals !== undefined) {
      return fieldValue === condition.equals;
    }
    if (condition.not_equals !== undefined) {
      return fieldValue !== condition.not_equals;
    }
    if (condition.contains !== undefined && Array.isArray(fieldValue)) {
      return fieldValue.includes(condition.contains);
    }
    if (condition.is_empty !== undefined) {
      const isEmpty = !fieldValue || (Array.isArray(fieldValue) && fieldValue.length === 0);
      return condition.is_empty ? isEmpty : !isEmpty;
    }
    if (condition.is_not_empty !== undefined) {
      const isEmpty = !fieldValue || (Array.isArray(fieldValue) && fieldValue.length === 0);
      return condition.is_not_empty ? !isEmpty : isEmpty;
    }

    return true;
  }, [values]);

  // Render a section with proper key and value binding
  const renderSection = useCallback((section, keyPrefix) => {
    // Check show_if condition
    if (section.show_if && !evaluateCondition(section.show_if)) {
      return null;
    }

    const key = section.input_name || section.label || section.prompt || keyPrefix;

    return (
      <UISection
        key={keyPrefix}
        spec={section}
        value={values[key]}
        error={errors[key]}
        onChange={(v) => handleChange(key, v)}
        phaseOutput={phaseOutput}
        values={values}
        onValueChange={handleChange}
        renderSection={renderSection}
        checkpointId={checkpointId}
        sessionId={sessionId}
      />
    );
  }, [values, errors, phaseOutput, handleChange, evaluateCondition, checkpointId, sessionId]);

  const layout = spec?.layout || 'vertical';

  // Check if any section has type "html" (HTMX handles its own submission)
  const hasHTMLSection = React.useMemo(() => {
    const checkSections = (sections) => {
      if (!sections) return false;
      return sections.some(s => {
        if (s.type === 'html') return true;
        // Check nested sections in tabs, groups, columns
        if (s.tabs) return s.tabs.some(tab => checkSections(tab.sections));
        if (s.sections) return checkSections(s.sections);
        return false;
      });
    };

    // Check main sections
    if (checkSections(spec?.sections)) return true;

    // Check column sections
    if (spec?.columns) {
      return spec.columns.some(col => checkSections(col.sections));
    }

    return false;
  }, [spec]);

  // Render multi-column layouts
  const renderLayout = () => {
    switch (layout) {
      case 'two-column':
        return (
          <TwoColumnLayout
            spec={spec}
            renderSection={renderSection}
          />
        );

      case 'three-column':
      case 'grid':
        return (
          <GridLayout
            spec={spec}
            renderSection={renderSection}
          />
        );

      case 'sidebar-left':
        return (
          <SidebarLayout
            spec={spec}
            renderSection={renderSection}
            position="left"
          />
        );

      case 'sidebar-right':
        return (
          <SidebarLayout
            spec={spec}
            renderSection={renderSection}
            position="right"
          />
        );

      default: // vertical, horizontal
        return (
          <div className="dynamic-ui-sections">
            {(spec?.sections || []).map((section, idx) =>
              renderSection(section, `section_${idx}`)
            )}
          </div>
        );
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className={`dynamic-ui layout-${layout}`}
    >
      {spec?.title && (
        <h3 className="dynamic-ui-title">{spec.title}</h3>
      )}
      {spec?.subtitle && (
        <p className="dynamic-ui-subtitle">{spec.subtitle}</p>
      )}

      {renderLayout()}

      {/* Only show submit button if no HTMX section (HTMX handles its own submission) */}
      {!hasHTMLSection && (
        <div className="dynamic-ui-actions">
          {spec?.show_cancel && (
            <button
              type="button"
              className="dynamic-ui-cancel"
            >
              {spec.cancel_label || 'Cancel'}
            </button>
          )}
          <button
            type="submit"
            disabled={isLoading}
            className="dynamic-ui-submit"
          >
            {isLoading ? 'Submitting...' : (spec?.submit_label || 'Submit')}
          </button>
        </div>
      )}
    </form>
  );
}

/**
 * Renders a single UI section based on its type
 */
function UISection({ spec, value, error, onChange, phaseOutput, values, onValueChange, renderSection, checkpointId, sessionId }) {
  switch (spec.type) {
    // Existing section types
    case 'preview':
      return <PreviewSection spec={spec} phaseOutput={phaseOutput} />;
    case 'header':
      return <HeaderSection spec={spec} />;
    case 'confirmation':
      return <ConfirmationSection spec={spec} value={value} onChange={onChange} />;
    case 'choice':
      return <ChoiceSection spec={spec} value={value} error={error} onChange={onChange} />;
    case 'multi_choice':
      return <MultiChoiceSection spec={spec} value={value} error={error} onChange={onChange} />;
    case 'rating':
      return <RatingSection spec={spec} value={value} onChange={onChange} />;
    case 'text':
      // If has 'content' property, treat as display text (like preview)
      if (spec.content) {
        return <TextDisplaySection spec={spec} />;
      }
      // Otherwise, treat as input
      return <TextSection spec={spec} value={value} error={error} onChange={onChange} />;
    case 'text_input':
      return <TextSection spec={spec} value={value} error={error} onChange={onChange} />;
    case 'slider':
      return <SliderSection spec={spec} value={value} onChange={onChange} />;
    case 'form':
      return <FormSection spec={spec} value={value} error={error} onChange={onChange} />;
    case 'group':
      return <GroupSection spec={spec} value={value} error={error} onChange={onChange} phaseOutput={phaseOutput} renderSection={renderSection} />;

    // NEW: Rich content section types
    case 'image':
      return <ImageSection spec={spec} />;
    case 'data_table':
      return <DataTableSection spec={spec} value={value} onChange={onChange} />;
    case 'code':
      return <CodeSection spec={spec} />;
    case 'card_grid':
      return <CardGridSection spec={spec} value={value} onChange={onChange} />;
    case 'comparison':
      return <ComparisonSection spec={spec} value={value} onChange={onChange} />;
    case 'accordion':
      return <AccordionSection spec={spec} />;
    case 'tabs':
      return <TabsSection spec={spec} renderSection={renderSection} />;

    // HTMX: Raw HTML with HTMX attributes
    case 'html':
      return <HTMLSection spec={spec} checkpointId={checkpointId} sessionId={sessionId} />;

    // Submit section (from backend) - skip rendering, HTMX handles its own submission
    case 'submit':
      return null;

    default:
      return <div className="ui-section unknown">Unknown section type: {spec.type}</div>;
  }
}

/**
 * Header Section - Renders a heading with optional icon
 */
function HeaderSection({ spec }) {
  const level = spec.level || 2;
  const text = spec.text || spec.content || '';
  const icon = spec.icon;
  const HeaderTag = `h${level}`;

  return (
    <div className="ui-section header">
      <HeaderTag className="section-heading">
        {icon && <span className="heading-icon">{icon}</span>}
        {text}
      </HeaderTag>
    </div>
  );
}

/**
 * Text Display Section - Renders static text with optional styling
 */
function TextDisplaySection({ spec }) {
  const content = spec.content || '';
  const style = spec.style || 'normal';

  return (
    <div className={`ui-section text-display ${style}`}>
      <p className="display-text">{content}</p>
    </div>
  );
}

/**
 * Preview Section - Renders phase output in different formats
 */
function PreviewSection({ spec, phaseOutput }) {
  const content = spec.content || phaseOutput || '';
  const render = spec.render || 'auto';
  const [collapsed, setCollapsed] = useState(spec.collapsible && spec.default_collapsed);

  // Auto-detect render type if set to 'auto'
  const detectRenderType = (text) => {
    if (!text) return 'text';
    const trimmed = text.trim();

    // Check for code blocks
    if (trimmed.startsWith('```') || trimmed.startsWith('def ') || trimmed.startsWith('class ') || trimmed.startsWith('function ')) {
      return 'code';
    }

    // Check for markdown
    if (/^#+\s|^\*\*|\[.*\]\(|^-\s/.test(trimmed)) {
      return 'markdown';
    }

    // Check for JSON
    if ((trimmed.startsWith('{') || trimmed.startsWith('[')) && (trimmed.endsWith('}') || trimmed.endsWith(']'))) {
      try {
        JSON.parse(trimmed);
        return 'code';
      } catch {}
    }

    return 'text';
  };

  const actualRender = render === 'auto' ? detectRenderType(content) : render;

  const renderContent = () => {
    switch (actualRender) {
      case 'markdown':
        return (
          <div className="preview-markdown">
            <RichMarkdown
              components={{
                code({ node, inline, className, children, ...props }) {
                  const match = /language-(\w+)/.exec(className || '');
                  return !inline && match ? (
                    <SyntaxHighlighter
                      style={vscDarkPlus}
                      language={match[1]}
                      PreTag="div"
                      {...props}
                    >
                      {String(children).replace(/\n$/, '')}
                    </SyntaxHighlighter>
                  ) : (
                    <code className={className} {...props}>
                      {children}
                    </code>
                  );
                }
              }}
            >
              {content}
            </RichMarkdown>
          </div>
        );
      case 'code':
        return (
          <SyntaxHighlighter
            language="javascript"
            style={vscDarkPlus}
            customStyle={{ margin: 0, borderRadius: '6px' }}
          >
            {content}
          </SyntaxHighlighter>
        );
      case 'image':
        return <img src={content} alt="Output" className="preview-image" />;
      default:
        return <pre className="preview-text">{content}</pre>;
    }
  };

  return (
    <div className="ui-section preview">
      {spec.collapsible && (
        <button
          type="button"
          className="preview-toggle"
          onClick={() => setCollapsed(!collapsed)}
        >
          {collapsed ? '▶' : '▼'} Output
        </button>
      )}
      {!collapsed && (
        <div
          className="preview-content"
          style={{ maxHeight: spec.max_height || 400 }}
        >
          {renderContent()}
        </div>
      )}
    </div>
  );
}

/**
 * Confirmation Section - Yes/No with optional custom labels
 */
function ConfirmationSection({ spec, value, onChange }) {
  return (
    <div className="ui-section confirmation">
      <p className="section-prompt">{spec.prompt || 'Proceed?'}</p>
      <div className="confirmation-buttons">
        <button
          type="button"
          onClick={() => onChange({ confirmed: true })}
          className={`confirm-btn yes ${value?.confirmed === true ? 'selected' : ''}`}
        >
          {spec.yes_label || 'Yes'}
        </button>
        <button
          type="button"
          onClick={() => onChange({ confirmed: false })}
          className={`confirm-btn no ${value?.confirmed === false ? 'selected' : ''}`}
        >
          {spec.no_label || 'No'}
        </button>
      </div>
    </div>
  );
}

/**
 * Choice Section - Radio buttons for single selection
 */
function ChoiceSection({ spec, value, error, onChange }) {
  const options = spec.options || [];

  return (
    <div className="ui-section choice">
      <label className="section-label">
        {spec.label || spec.prompt}
        {spec.required && <span className="required">*</span>}
      </label>
      {error && <p className="section-error">{error}</p>}
      <div className="choice-options">
        {options.map((option, idx) => (
          <label
            key={idx}
            className={`choice-option ${value === option.value ? 'selected' : ''} ${option.disabled ? 'disabled' : ''}`}
          >
            <input
              type="radio"
              name={`choice_${spec.label || idx}`}
              value={option.value}
              checked={value === option.value}
              onChange={() => onChange(option.value)}
              disabled={option.disabled}
            />
            <div className="option-content">
              {option.icon && <span className="option-icon">{option.icon}</span>}
              <span className="option-label">{option.label}</span>
              {option.description && (
                <span className="option-description">{option.description}</span>
              )}
            </div>
          </label>
        ))}
      </div>
    </div>
  );
}

/**
 * Multi-Choice Section - Checkboxes for multiple selection
 */
function MultiChoiceSection({ spec, value, error, onChange }) {
  const options = spec.options || [];
  const selected = value || [];

  const handleToggle = (optionValue) => {
    const newSelected = selected.includes(optionValue)
      ? selected.filter(v => v !== optionValue)
      : [...selected, optionValue];
    onChange(newSelected);
  };

  return (
    <div className="ui-section multi-choice">
      <label className="section-label">
        {spec.label || spec.prompt}
        {spec.required && <span className="required">*</span>}
      </label>
      {spec.min && spec.max && (
        <span className="selection-hint">Select {spec.min}-{spec.max} options</span>
      )}
      {error && <p className="section-error">{error}</p>}
      <div className="multi-choice-options">
        {options.map((option, idx) => (
          <label
            key={idx}
            className={`multi-choice-option ${selected.includes(option.value) ? 'selected' : ''}`}
          >
            <input
              type="checkbox"
              checked={selected.includes(option.value)}
              onChange={() => handleToggle(option.value)}
            />
            <div className="option-content">
              <span className="option-label">{option.label}</span>
              {option.description && (
                <span className="option-description">{option.description}</span>
              )}
            </div>
          </label>
        ))}
      </div>
    </div>
  );
}

/**
 * Rating Section - Star or labeled scale rating
 */
function RatingSection({ spec, value, onChange }) {
  const maxRating = spec.max || 5;
  const labels = spec.labels || null;
  const showValue = spec.show_value !== false;

  return (
    <div className="ui-section rating">
      <label className="section-label">{spec.label || spec.prompt || 'Rate this'}</label>
      <div className="rating-container">
        <div className="rating-stars">
          {[...Array(maxRating)].map((_, idx) => {
            const ratingValue = idx + 1;
            const label = labels ? labels[idx] : null;
            return (
              <button
                key={idx}
                type="button"
                onClick={() => onChange(ratingValue)}
                className={`rating-star ${value >= ratingValue ? 'filled' : ''}`}
                title={label || `${ratingValue} / ${maxRating}`}
              >
                {value >= ratingValue ? '★' : '☆'}
              </button>
            );
          })}
        </div>
        {showValue && value && (
          <span className="rating-value">
            {value}/{maxRating}
            {labels && labels[value - 1] && ` - ${labels[value - 1]}`}
          </span>
        )}
      </div>
      {labels && (
        <div className="rating-labels">
          {labels.map((label, idx) => (
            <span key={idx} className={`rating-label ${value === idx + 1 ? 'active' : ''}`}>
              {label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Text Section - Free text input (single or multiline)
 */
function TextSection({ spec, value, error, onChange }) {
  const isMultiline = spec.multiline !== false;
  // Handle both 'required' and 'optional' properties
  // optional: true means not required, so invert it
  const isRequired = spec.required || (spec.optional === false);

  return (
    <div className="ui-section text">
      <label className="section-label">
        {spec.label || spec.prompt}
        {isRequired && <span className="required">*</span>}
      </label>
      {error && <p className="section-error">{error}</p>}
      {isMultiline ? (
        <textarea
          value={value || ''}
          onChange={(e) => onChange(e.target.value)}
          placeholder={spec.placeholder || ''}
          rows={spec.rows || 4}
          maxLength={spec.max_length}
          required={isRequired}
          className="text-input multiline"
        />
      ) : (
        <input
          type="text"
          value={value || ''}
          onChange={(e) => onChange(e.target.value)}
          placeholder={spec.placeholder || ''}
          maxLength={spec.max_length}
          required={isRequired}
          className="text-input"
        />
      )}
      {spec.max_length && (
        <span className="char-count">
          {(value || '').length}/{spec.max_length}
        </span>
      )}
    </div>
  );
}

/**
 * Slider Section - Range input with labels
 */
function SliderSection({ spec, value, onChange }) {
  const min = spec.min || 0;
  const max = spec.max || 100;
  const step = spec.step || 1;
  const currentValue = value ?? spec.default ?? Math.floor((min + max) / 2);

  return (
    <div className="ui-section slider">
      <label className="section-label">
        {spec.label || spec.prompt}
        {spec.show_value !== false && (
          <span className="slider-value">{currentValue}</span>
        )}
      </label>
      <div className="slider-container">
        <span className="slider-min">{spec.labels?.[min] || min}</span>
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={currentValue}
          onChange={(e) => onChange(Number(e.target.value))}
          className="slider-input"
        />
        <span className="slider-max">{spec.labels?.[max] || max}</span>
      </div>
    </div>
  );
}

/**
 * Form Section - Multiple form fields
 */
function FormSection({ spec, value, error, onChange }) {
  const fields = spec.fields || [];
  const formValue = value || {};

  const handleFieldChange = (fieldName, fieldValue) => {
    onChange({ ...formValue, [fieldName]: fieldValue });
  };

  return (
    <div className="ui-section form">
      {spec.label && <h4 className="form-title">{spec.label}</h4>}
      <div className="form-fields">
        {fields.map((field, idx) => (
          <FormField
            key={idx}
            field={field}
            value={formValue[field.name]}
            onChange={(v) => handleFieldChange(field.name, v)}
          />
        ))}
      </div>
    </div>
  );
}

/**
 * Individual form field renderer
 */
function FormField({ field, value, onChange }) {
  switch (field.type) {
    case 'text':
    case 'email':
    case 'url':
    case 'password':
      return (
        <div className="form-field">
          <label className="field-label">
            {field.label}
            {field.required && <span className="required">*</span>}
          </label>
          <input
            type={field.type}
            value={value || ''}
            onChange={(e) => onChange(e.target.value)}
            placeholder={field.placeholder}
            required={field.required}
            className="field-input"
          />
        </div>
      );
    case 'number':
      return (
        <div className="form-field">
          <label className="field-label">
            {field.label}
            {field.required && <span className="required">*</span>}
          </label>
          <input
            type="number"
            value={value ?? ''}
            onChange={(e) => onChange(Number(e.target.value))}
            min={field.min}
            max={field.max}
            step={field.step}
            required={field.required}
            className="field-input"
          />
        </div>
      );
    case 'textarea':
      return (
        <div className="form-field">
          <label className="field-label">
            {field.label}
            {field.required && <span className="required">*</span>}
          </label>
          <textarea
            value={value || ''}
            onChange={(e) => onChange(e.target.value)}
            placeholder={field.placeholder}
            rows={field.rows || 3}
            required={field.required}
            className="field-textarea"
          />
        </div>
      );
    case 'select':
      return (
        <div className="form-field">
          <label className="field-label">
            {field.label}
            {field.required && <span className="required">*</span>}
          </label>
          <select
            value={value || ''}
            onChange={(e) => onChange(e.target.value)}
            required={field.required}
            className="field-select"
          >
            <option value="">Select...</option>
            {(field.options || []).map((opt, idx) => (
              <option key={idx} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      );
    case 'checkbox':
      return (
        <div className="form-field checkbox">
          <label className="field-checkbox-label">
            <input
              type="checkbox"
              checked={value || false}
              onChange={(e) => onChange(e.target.checked)}
            />
            <span>{field.label}</span>
          </label>
        </div>
      );
    default:
      return (
        <div className="form-field">
          <label className="field-label">{field.label}</label>
          <input
            type="text"
            value={value || ''}
            onChange={(e) => onChange(e.target.value)}
            className="field-input"
          />
        </div>
      );
  }
}

/**
 * Group Section - Nested sections with optional collapsibility
 */
function GroupSection({ spec, value, error, onChange, phaseOutput, renderSection }) {
  const [collapsed, setCollapsed] = useState(spec.default_collapsed);

  return (
    <div className={`ui-section group ${collapsed ? 'collapsed' : ''}`}>
      <div className="group-header" onClick={() => spec.collapsible && setCollapsed(!collapsed)}>
        {spec.collapsible && (
          <span className="group-toggle">{collapsed ? '▶' : '▼'}</span>
        )}
        <h4 className="group-title">{spec.label}</h4>
      </div>
      {!collapsed && (
        <div className="group-content">
          {(spec.sections || []).map((section, idx) =>
            renderSection ? renderSection(section, `group_${idx}`) : (
              <UISection
                key={idx}
                spec={section}
                value={value}
                error={error}
                onChange={onChange}
                phaseOutput={phaseOutput}
              />
            )
          )}
        </div>
      )}
    </div>
  );
}

export default DynamicUI;
