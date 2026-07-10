export const THEME_STORAGE_KEY = 'blog-style-v2';
export const DEFAULT_THEME_ID = 'crayon-party';

export const THEMES = [
	{
		id: 'crayon-party',
		label: '蜡笔派对',
		swatch: 'conic-gradient(from 140deg, #2f7fe6, #fff2d5, #f04f9a, #ffbe3e)',
	},
	{
		id: 'paper',
		label: '纸刊手记',
		swatch: 'conic-gradient(from 140deg, #c4492d, #fff8e8, #0d7f78, #c4492d)',
	},
	{
		id: 'noir',
		label: '夜读小报',
		swatch: 'conic-gradient(from 140deg, #f06d4f, #10100d, #4fc3c9, #ffb35c)',
	},
	{
		id: 'ceramic',
		label: '陶瓷档案',
		swatch: 'conic-gradient(from 140deg, #1f6f8b, #fafffd, #b23a34, #1f6f8b)',
	},
	{
		id: 'brutal',
		label: '粗野印刷',
		swatch: 'conic-gradient(from 140deg, #12110f, #fffdee, #ffd537, #d83324)',
	},
	{
		id: 'terminal',
		label: '绿色终端',
		swatch: 'conic-gradient(from 140deg, #7dff9e, #040e0a, #ffdc5e, #ff6c4f)',
	},
] as const;

export const THEME_IDS = THEMES.map((theme) => theme.id);
export const DARK_THEME_IDS = ['noir', 'terminal'] as const;
