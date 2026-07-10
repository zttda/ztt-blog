import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

const blog = defineCollection({
	// Load Markdown and MDX files in the `src/content/blog/` directory.
	loader: glob({ base: './src/content/blog', pattern: '**/*.{md,mdx}' }),
	// Type-check frontmatter using a schema
	schema: ({ image }) =>
		z.object({
			title: z.string().trim().min(1, '文章标题不能为空').max(80, '文章标题最多 80 个字符'),
			description: z.string().trim().min(1, '文章摘要不能为空').max(180, '文章摘要最多 180 个字符'),
			tags: z.array(z.string().trim().min(1).max(30)).max(8, '一篇文章最多使用 8 个标签').default([]),
			// Missing draft metadata must fail closed instead of publishing by accident.
			draft: z.boolean().default(true),
			// Transform string to Date object
			pubDate: z.coerce.date(),
			updatedDate: z.coerce.date().optional(),
			heroImage: z.optional(image()),
		}),
});

export const collections = { blog };
