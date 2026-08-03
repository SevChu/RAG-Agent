declare module 'markdown-it' {
  export interface MarkdownItOptions {
    html?: boolean
    breaks?: boolean
    linkify?: boolean
  }

  export default class MarkdownIt {
    constructor(options?: MarkdownItOptions)
    render(source: string): string
  }
}
