/* ===========================================================================
   AlphaLearn – FRQ Playground
   Multi-step wizard for generating, writing, and grading AP FRQs.
   =========================================================================== */

(function () {
    'use strict';

    /* ======================================================================
       AP RUBRIC DATA
       Complete rubric definitions for every supported AP subject/FRQ type.
       ====================================================================== */

    var AP_SUBJECTS = {
        'ap-us-history': {
            name: 'AP US History',
            shortName: 'APUSH',
            icon: 'fa-landmark',
            iconClass: 'history',
            category: 'history',
        },
        'ap-world-history': {
            name: 'AP World History: Modern',
            shortName: 'AP World',
            icon: 'fa-globe',
            iconClass: 'history',
            category: 'history',
        },
        'ap-euro-history': {
            name: 'AP European History',
            shortName: 'AP Euro',
            icon: 'fa-chess-rook',
            iconClass: 'history',
            category: 'history',
        },
        'ap-gov': {
            name: 'AP US Government & Politics',
            shortName: 'AP Gov',
            icon: 'fa-gavel',
            iconClass: 'social',
            category: 'government',
        },
        'ap-english-lang': {
            name: 'AP English Language & Composition',
            shortName: 'AP Lang',
            icon: 'fa-book-open',
            iconClass: 'english',
            category: 'english-lang',
        },
        'ap-english-lit': {
            name: 'AP English Literature & Composition',
            shortName: 'AP Lit',
            icon: 'fa-feather-pointed',
            iconClass: 'english',
            category: 'english-lit',
        },
        'ap-biology': {
            name: 'AP Biology',
            shortName: 'AP Bio',
            icon: 'fa-dna',
            iconClass: 'science',
            category: 'science-bio',
        },
        'ap-chemistry': {
            name: 'AP Chemistry',
            shortName: 'AP Chem',
            icon: 'fa-flask',
            iconClass: 'science',
            category: 'science-chem',
        },
        'ap-physics-1': {
            name: 'AP Physics 1',
            shortName: 'AP Physics 1',
            icon: 'fa-atom',
            iconClass: 'science',
            category: 'science-physics',
        },
        'ap-physics-2': {
            name: 'AP Physics 2',
            shortName: 'AP Physics 2',
            icon: 'fa-atom',
            iconClass: 'science',
            category: 'science-physics',
        },
        'ap-physics-c-mech': {
            name: 'AP Physics C: Mechanics',
            shortName: 'AP Physics C: Mech',
            icon: 'fa-atom',
            iconClass: 'science',
            category: 'science-physics',
        },
        'ap-physics-c-em': {
            name: 'AP Physics C: E&M',
            shortName: 'AP Physics C: E&M',
            icon: 'fa-atom',
            iconClass: 'science',
            category: 'science-physics',
        },
        'ap-calculus-ab': {
            name: 'AP Calculus AB',
            shortName: 'AP Calc AB',
            icon: 'fa-calculator',
            iconClass: 'math',
            category: 'math-calc',
        },
        'ap-calculus-bc': {
            name: 'AP Calculus BC',
            shortName: 'AP Calc BC',
            icon: 'fa-calculator',
            iconClass: 'math',
            category: 'math-calc',
        },
        'ap-statistics': {
            name: 'AP Statistics',
            shortName: 'AP Stats',
            icon: 'fa-chart-bar',
            iconClass: 'math',
            category: 'math-stats',
        },
        'ap-environmental': {
            name: 'AP Environmental Science',
            shortName: 'AP Enviro',
            icon: 'fa-leaf',
            iconClass: 'science',
            category: 'science-enviro',
        },
        'ap-psychology': {
            name: 'AP Psychology',
            shortName: 'AP Psych',
            icon: 'fa-brain',
            iconClass: 'social',
            category: 'psychology',
        },
        'ap-cs-a': {
            name: 'AP Computer Science A',
            shortName: 'AP CS A',
            icon: 'fa-code',
            iconClass: 'cs',
            category: 'cs',
        },
        'ap-human-geo': {
            name: 'AP Human Geography',
            shortName: 'AP Human Geo',
            icon: 'fa-map',
            iconClass: 'social',
            category: 'human-geo',
        },
    };

    var AP_FRQ_TYPES = {
        /* ── History (APUSH, World, Euro) ───────────── */
        history: [
            {
                id: 'dbq',
                name: 'Document-Based Question (DBQ)',
                points: 7,
                time: 60,
                desc: 'Analyze 7 historical documents and construct an argument with a thesis, contextualization, evidence, sourcing, and complexity.',
                rubric: [
                    { id: 'thesis', name: 'Thesis/Claim', max: 1, desc: 'Historically defensible thesis that establishes a line of reasoning.' },
                    { id: 'context', name: 'Contextualization', max: 1, desc: 'Describes broader historical context relevant to the prompt in multiple sentences.' },
                    { id: 'evidence-docs', name: 'Evidence from Documents', max: 2, desc: '1pt: describes 3+ docs. 2pts: uses 6+ docs to support argument.' },
                    { id: 'evidence-beyond', name: 'Evidence Beyond Documents', max: 1, desc: 'Uses at least one additional specific historical example beyond the documents.' },
                    { id: 'sourcing', name: 'Analysis & Reasoning (Sourcing)', max: 1, desc: 'Explains POV, purpose, historical situation, or audience for 3+ documents.' },
                    { id: 'complexity', name: 'Complexity', max: 1, desc: 'Demonstrates nuanced understanding through multiple variables, counterarguments, or cross-period connections.' },
                ],
                subSkills: [
                    { id: 'full', name: 'Full DBQ Essay', desc: 'Write the complete essay targeting all 7 rubric points.', points: '0-7' },
                    { id: 'thesis', name: 'Thesis Only', desc: 'Write just a thesis statement. Graded on whether it\'s historically defensible and establishes a line of reasoning.', points: '0-1' },
                    { id: 'context', name: 'Contextualization Only', desc: 'Write a contextualization paragraph placing the topic in broader historical context.', points: '0-1' },
                    { id: 'evidence-docs', name: 'Document Analysis', desc: 'Analyze the provided documents. Practice using 6+ docs to build an argument.', points: '0-2' },
                    { id: 'evidence-beyond', name: 'Outside Evidence', desc: 'Identify and explain relevant historical evidence NOT in the documents.', points: '0-1' },
                    { id: 'sourcing', name: 'Sourcing Practice', desc: 'Practice analyzing POV, purpose, historical situation, or audience for 3+ documents.', points: '0-1' },
                    { id: 'complexity', name: 'Complexity Point', desc: 'Demonstrate nuanced understanding through multiple perspectives or counterarguments.', points: '0-1' },
                ],
            },
            {
                id: 'leq',
                name: 'Long Essay Question (LEQ)',
                points: 6,
                time: 40,
                desc: 'Construct an argument using specific historical evidence from your own knowledge (no documents provided).',
                rubric: [
                    { id: 'thesis', name: 'Thesis/Claim', max: 1, desc: 'Historically defensible thesis that establishes a line of reasoning.' },
                    { id: 'context', name: 'Contextualization', max: 1, desc: 'Describes broader historical context relevant to the prompt.' },
                    { id: 'evidence', name: 'Evidence', max: 2, desc: '1pt: provides specific historical examples. 2pts: uses evidence to support the argument.' },
                    { id: 'analysis', name: 'Analysis & Reasoning', max: 1, desc: 'Uses historical reasoning (comparison, causation, CCOT) to frame the argument.' },
                    { id: 'complexity', name: 'Complexity', max: 1, desc: 'Demonstrates nuanced understanding through qualifications, multiple perspectives, or contradictions.' },
                ],
                subSkills: [
                    { id: 'full', name: 'Full LEQ Essay', desc: 'Write the complete essay targeting all 6 rubric points.', points: '0-6' },
                    { id: 'thesis', name: 'Thesis Only', desc: 'Write just a thesis statement with a clear line of reasoning.', points: '0-1' },
                    { id: 'context', name: 'Contextualization Only', desc: 'Write a contextualization paragraph.', points: '0-1' },
                    { id: 'evidence', name: 'Evidence Practice', desc: 'Provide specific historical evidence supporting an argument.', points: '0-2' },
                    { id: 'analysis', name: 'Analysis & Reasoning', desc: 'Practice framing arguments using historical reasoning skills.', points: '0-1' },
                    { id: 'complexity', name: 'Complexity Point', desc: 'Demonstrate nuanced understanding.', points: '0-1' },
                ],
            },
            {
                id: 'saq',
                name: 'Short Answer Question (SAQ)',
                points: 3,
                time: 13,
                desc: 'Answer 3 parts (a, b, c) in complete sentences using specific historical evidence.',
                rubric: [
                    { id: 'part-a', name: 'Part A', max: 1, desc: 'Accurately addresses the prompt with specific historical evidence.' },
                    { id: 'part-b', name: 'Part B', max: 1, desc: 'Accurately addresses the prompt with specific historical evidence.' },
                    { id: 'part-c', name: 'Part C', max: 1, desc: 'Accurately addresses the prompt with specific historical evidence.' },
                ],
                subSkills: [
                    { id: 'full', name: 'Full SAQ', desc: 'Answer all three parts of the SAQ.', points: '0-3' },
                ],
            },
        ],

        /* ── AP US Government ───────────────────────── */
        government: [
            {
                id: 'concept-app',
                name: 'Concept Application',
                points: 3,
                time: 20,
                desc: 'Respond to a political scenario by describing and explaining political institutions, behaviors, or processes.',
                rubric: [
                    { id: 'describe', name: 'Describe', max: 1, desc: 'Accurately describes a political institution, behavior, or process.' },
                    { id: 'explain', name: 'Explain', max: 1, desc: 'Explains the effects of the institution, behavior, or process.' },
                    { id: 'apply', name: 'Apply', max: 1, desc: 'Applies the concept to the given scenario with specific connection.' },
                ],
                subSkills: [{ id: 'full', name: 'Full Response', desc: 'Complete all parts.', points: '0-3' }],
            },
            {
                id: 'quant-analysis',
                name: 'Quantitative Analysis',
                points: 4,
                time: 20,
                desc: 'Analyze quantitative data (charts, graphs) and explain its political significance.',
                rubric: [
                    { id: 'identify', name: 'Identify Data', max: 1, desc: 'Accurately identifies data or trends from the visual.' },
                    { id: 'describe', name: 'Describe Pattern', max: 1, desc: 'Describes a pattern or trend in the data.' },
                    { id: 'explain', name: 'Draw Conclusion', max: 1, desc: 'Draws a conclusion about the data and its political meaning.' },
                    { id: 'connect', name: 'Connect to Concept', max: 1, desc: 'Connects the data to a broader political principle or process.' },
                ],
                subSkills: [{ id: 'full', name: 'Full Response', desc: 'Complete all parts.', points: '0-4' }],
            },
            {
                id: 'scotus',
                name: 'SCOTUS Comparison',
                points: 4,
                time: 20,
                desc: 'Compare a non-required Supreme Court case with a required case, explaining similarities and significance.',
                rubric: [
                    { id: 'identify', name: 'Identify Facts', max: 1, desc: 'Identifies the facts of the non-required case.' },
                    { id: 'describe', name: 'Describe Required Case', max: 1, desc: 'Describes the ruling or holding of the required case.' },
                    { id: 'compare', name: 'Compare Cases', max: 1, desc: 'Explains a similarity or difference between the cases.' },
                    { id: 'connect', name: 'Constitutional Principle', max: 1, desc: 'Connects the comparison to a constitutional principle.' },
                ],
                subSkills: [{ id: 'full', name: 'Full Response', desc: 'Complete all parts.', points: '0-4' }],
            },
            {
                id: 'argument-essay',
                name: 'Argument Essay',
                points: 6,
                time: 40,
                desc: 'Develop an argument essay using evidence from foundational documents and course concepts.',
                rubric: [
                    { id: 'thesis', name: 'Thesis/Claim', max: 1, desc: 'Presents a defensible claim or thesis that responds to the prompt.' },
                    { id: 'evidence', name: 'Evidence', max: 3, desc: '1pt: one relevant piece. 2pts: two from foundational documents. 3pts: evidence supports reasoning throughout.' },
                    { id: 'reasoning', name: 'Reasoning', max: 1, desc: 'Explains how the evidence supports the thesis using political principles.' },
                    { id: 'rebuttal', name: 'Respond to Opposing View', max: 1, desc: 'Responds to an opposing or alternative perspective.' },
                ],
                subSkills: [
                    { id: 'full', name: 'Full Argument Essay', desc: 'Write the complete essay.', points: '0-6' },
                    { id: 'thesis', name: 'Thesis Only', desc: 'Write just a defensible thesis.', points: '0-1' },
                    { id: 'evidence', name: 'Evidence from Foundational Documents', desc: 'Practice citing and integrating foundational documents.', points: '0-3' },
                    { id: 'reasoning', name: 'Reasoning & Organization', desc: 'Practice building a clear line of reasoning.', points: '0-1' },
                ],
            },
        ],

        /* ── AP English Language ────────────────────── */
        'english-lang': [
            {
                id: 'synthesis',
                name: 'Synthesis Essay',
                points: 6,
                time: 55,
                desc: 'Read 6-7 sources and develop a position, incorporating at least 3 sources as evidence.',
                rubric: [
                    { id: 'thesis', name: 'Thesis', max: 1, desc: 'Defensible position that responds to the prompt.' },
                    { id: 'evidence', name: 'Evidence & Commentary', max: 4, desc: '1pt: 2 sources. 2pts: 3 sources, some explanation. 3pts: specific evidence, explains reasoning. 4pts: consistently explains how evidence supports line of reasoning.' },
                    { id: 'sophistication', name: 'Sophistication', max: 1, desc: 'Demonstrates sophistication of thought and/or a complex understanding of the rhetorical situation.' },
                ],
                subSkills: [
                    { id: 'full', name: 'Full Synthesis Essay', desc: 'Write the complete essay using sources.', points: '0-6' },
                    { id: 'thesis', name: 'Thesis Only', desc: 'Write just a defensible thesis responding to the prompt.', points: '0-1' },
                    { id: 'evidence', name: 'Evidence & Commentary', desc: 'Practice integrating and explaining source evidence.', points: '0-4' },
                    { id: 'sophistication', name: 'Sophistication', desc: 'Practice demonstrating complex understanding.', points: '0-1' },
                ],
            },
            {
                id: 'rhetorical-analysis',
                name: 'Rhetorical Analysis',
                points: 6,
                time: 40,
                desc: 'Analyze how an author uses rhetorical strategies to achieve their purpose.',
                rubric: [
                    { id: 'thesis', name: 'Thesis', max: 1, desc: 'Defensible claim that analyzes the writer\'s rhetorical choices.' },
                    { id: 'evidence', name: 'Evidence & Commentary', max: 4, desc: 'Provides specific evidence and explains how rhetorical choices build the writer\'s argument.' },
                    { id: 'sophistication', name: 'Sophistication', max: 1, desc: 'Demonstrates sophistication of thought and/or a complex understanding.' },
                ],
                subSkills: [
                    { id: 'full', name: 'Full Rhetorical Analysis', desc: 'Write the complete analysis.', points: '0-6' },
                    { id: 'thesis', name: 'Thesis Only', desc: 'Write a defensible thesis analyzing rhetorical choices.', points: '0-1' },
                    { id: 'evidence', name: 'Evidence & Commentary', desc: 'Practice analyzing specific rhetorical strategies.', points: '0-4' },
                    { id: 'sophistication', name: 'Sophistication', desc: 'Practice complex rhetorical understanding.', points: '0-1' },
                ],
            },
            {
                id: 'argument',
                name: 'Argument Essay',
                points: 6,
                time: 40,
                desc: 'Develop an evidence-based argument in response to a given topic.',
                rubric: [
                    { id: 'thesis', name: 'Thesis', max: 1, desc: 'Defensible position that responds to the prompt.' },
                    { id: 'evidence', name: 'Evidence & Commentary', max: 4, desc: 'Uses specific, relevant evidence with consistent explanation of how it supports reasoning.' },
                    { id: 'sophistication', name: 'Sophistication', max: 1, desc: 'Demonstrates sophistication of thought and/or complex understanding.' },
                ],
                subSkills: [
                    { id: 'full', name: 'Full Argument Essay', desc: 'Write the complete argument.', points: '0-6' },
                    { id: 'thesis', name: 'Thesis Only', desc: 'Write a defensible thesis.', points: '0-1' },
                    { id: 'evidence', name: 'Evidence & Commentary', desc: 'Practice supporting claims with evidence.', points: '0-4' },
                    { id: 'sophistication', name: 'Sophistication', desc: 'Practice nuanced argumentation.', points: '0-1' },
                ],
            },
        ],

        /* ── AP English Literature ──────────────────── */
        'english-lit': [
            {
                id: 'poetry-analysis',
                name: 'Poetry Analysis',
                points: 6,
                time: 40,
                desc: 'Analyze how a poem\'s literary elements contribute to its meaning.',
                rubric: [
                    { id: 'thesis', name: 'Thesis', max: 1, desc: 'Defensible interpretation of the poem.' },
                    { id: 'evidence', name: 'Evidence & Commentary', max: 4, desc: 'Specific evidence with explanation of how literary elements contribute to meaning.' },
                    { id: 'sophistication', name: 'Sophistication', max: 1, desc: 'Demonstrates sophistication in interpretation.' },
                ],
                subSkills: [
                    { id: 'full', name: 'Full Poetry Analysis', desc: 'Write the complete analysis.', points: '0-6' },
                    { id: 'thesis', name: 'Thesis Only', desc: 'Write a defensible interpretation thesis.', points: '0-1' },
                    { id: 'evidence', name: 'Evidence & Commentary', desc: 'Practice analyzing poetic devices.', points: '0-4' },
                    { id: 'sophistication', name: 'Sophistication', desc: 'Practice nuanced literary analysis.', points: '0-1' },
                ],
            },
            {
                id: 'prose-analysis',
                name: 'Prose Fiction Analysis',
                points: 6,
                time: 40,
                desc: 'Analyze how a prose passage\'s literary elements contribute to its meaning.',
                rubric: [
                    { id: 'thesis', name: 'Thesis', max: 1, desc: 'Defensible interpretation of the prose passage.' },
                    { id: 'evidence', name: 'Evidence & Commentary', max: 4, desc: 'Specific textual evidence with explanation of literary techniques.' },
                    { id: 'sophistication', name: 'Sophistication', max: 1, desc: 'Demonstrates sophistication in interpretation.' },
                ],
                subSkills: [
                    { id: 'full', name: 'Full Prose Analysis', desc: 'Write the complete analysis.', points: '0-6' },
                    { id: 'thesis', name: 'Thesis Only', desc: 'Write a defensible interpretation thesis.', points: '0-1' },
                    { id: 'evidence', name: 'Evidence & Commentary', desc: 'Practice analyzing prose techniques.', points: '0-4' },
                    { id: 'sophistication', name: 'Sophistication', desc: 'Practice nuanced literary analysis.', points: '0-1' },
                ],
            },
            {
                id: 'literary-argument',
                name: 'Literary Argument',
                points: 6,
                time: 40,
                desc: 'Analyze a concept or element in a work of literature you choose.',
                rubric: [
                    { id: 'thesis', name: 'Thesis', max: 1, desc: 'Defensible interpretation related to the prompt.' },
                    { id: 'evidence', name: 'Evidence & Commentary', max: 4, desc: 'Specific textual evidence with literary analysis.' },
                    { id: 'sophistication', name: 'Sophistication', max: 1, desc: 'Demonstrates sophistication in interpretation.' },
                ],
                subSkills: [
                    { id: 'full', name: 'Full Literary Argument', desc: 'Write the complete essay.', points: '0-6' },
                    { id: 'thesis', name: 'Thesis Only', desc: 'Write a defensible thesis.', points: '0-1' },
                    { id: 'evidence', name: 'Evidence & Commentary', desc: 'Practice textual evidence and analysis.', points: '0-4' },
                    { id: 'sophistication', name: 'Sophistication', desc: 'Practice nuanced argumentation.', points: '0-1' },
                ],
            },
        ],

        /* ── AP Biology ─────────────────────────────── */
        'science-bio': [
            {
                id: 'long-frq',
                name: 'Long Free Response',
                points: 8,
                time: 25,
                desc: 'Multi-part question requiring analysis of biological concepts, experimental design, and data interpretation.',
                rubric: [
                    { id: 'part-a', name: 'Part A', max: 2, desc: 'Accurately addresses the first prompt component.' },
                    { id: 'part-b', name: 'Part B', max: 3, desc: 'Accurately addresses the second prompt component with evidence.' },
                    { id: 'part-c', name: 'Part C', max: 3, desc: 'Accurately addresses the third prompt component.' },
                ],
                subSkills: [{ id: 'full', name: 'Full Response', desc: 'Answer all parts.', points: '0-8' }],
            },
            {
                id: 'short-frq',
                name: 'Short Free Response',
                points: 4,
                time: 10,
                desc: 'Focused question on a specific biological concept or data analysis.',
                rubric: [
                    { id: 'part-a', name: 'Part A', max: 2, desc: 'Accurately describes or identifies the concept.' },
                    { id: 'part-b', name: 'Part B', max: 2, desc: 'Explains or justifies with biological reasoning.' },
                ],
                subSkills: [{ id: 'full', name: 'Full Response', desc: 'Answer all parts.', points: '0-4' }],
            },
        ],

        /* ── AP Chemistry ───────────────────────────── */
        'science-chem': [
            {
                id: 'long-frq',
                name: 'Long Free Response',
                points: 10,
                time: 23,
                desc: 'Multi-part question involving calculations, molecular-level explanations, and conceptual reasoning.',
                rubric: [
                    { id: 'part-a', name: 'Part A', max: 3, desc: 'Calculations or identification with correct setup and answer.' },
                    { id: 'part-b', name: 'Part B', max: 4, desc: 'Explanation using chemical principles (Coulomb\'s law, equilibrium, etc.).' },
                    { id: 'part-c', name: 'Part C', max: 3, desc: 'Further analysis, prediction, or justification.' },
                ],
                subSkills: [{ id: 'full', name: 'Full Response', desc: 'Answer all parts.', points: '0-10' }],
            },
            {
                id: 'short-frq',
                name: 'Short Free Response',
                points: 4,
                time: 9,
                desc: 'Focused question on a specific chemistry concept or calculation.',
                rubric: [
                    { id: 'part-a', name: 'Part A', max: 2, desc: 'Correct identification or calculation.' },
                    { id: 'part-b', name: 'Part B', max: 2, desc: 'Explanation or justification.' },
                ],
                subSkills: [{ id: 'full', name: 'Full Response', desc: 'Answer all parts.', points: '0-4' }],
            },
        ],

        /* ── AP Physics ─────────────────────────────── */
        'science-physics': [
            {
                id: 'long-frq',
                name: 'Long Free Response',
                points: 12,
                time: 25,
                desc: 'Multi-part question with calculations, diagrams, and conceptual explanations.',
                rubric: [
                    { id: 'part-a', name: 'Part A', max: 3, desc: 'Correct setup, equations, and calculations.' },
                    { id: 'part-b', name: 'Part B', max: 3, desc: 'Analysis with correct physics principles.' },
                    { id: 'part-c', name: 'Part C', max: 3, desc: 'Diagram, graph, or further calculation.' },
                    { id: 'part-d', name: 'Part D', max: 3, desc: 'Explanation or prediction using reasoning.' },
                ],
                subSkills: [{ id: 'full', name: 'Full Response', desc: 'Answer all parts.', points: '0-12' }],
            },
            {
                id: 'short-frq',
                name: 'Short Free Response',
                points: 7,
                time: 15,
                desc: 'Focused question requiring calculation and brief explanation.',
                rubric: [
                    { id: 'part-a', name: 'Part A', max: 4, desc: 'Correct calculation or derivation.' },
                    { id: 'part-b', name: 'Part B', max: 3, desc: 'Conceptual explanation or prediction.' },
                ],
                subSkills: [{ id: 'full', name: 'Full Response', desc: 'Answer all parts.', points: '0-7' }],
            },
            {
                id: 'experimental',
                name: 'Experimental Design',
                points: 12,
                time: 25,
                desc: 'Design or analyze an experiment including variables, procedure, data analysis, and conclusions.',
                rubric: [
                    { id: 'design', name: 'Experimental Design', max: 4, desc: 'Identifies variables, controls, and procedure.' },
                    { id: 'data', name: 'Data Analysis', max: 4, desc: 'Correct analysis of provided or expected data.' },
                    { id: 'conclusion', name: 'Conclusion & Reasoning', max: 4, desc: 'Draws valid conclusion with physics reasoning.' },
                ],
                subSkills: [{ id: 'full', name: 'Full Response', desc: 'Answer all parts.', points: '0-12' }],
            },
        ],

        /* ── AP Calculus ────────────────────────────── */
        'math-calc': [
            {
                id: 'calculator-frq',
                name: 'Calculator FRQ (Part A)',
                points: 9,
                time: 30,
                desc: 'Multi-part question where a graphing calculator is required. Must show all work.',
                rubric: [
                    { id: 'part-a', name: 'Part A', max: 2, desc: 'Correct setup and answer.' },
                    { id: 'part-b', name: 'Part B', max: 3, desc: 'Correct method and computation.' },
                    { id: 'part-c', name: 'Part C', max: 2, desc: 'Correct analysis or interpretation.' },
                    { id: 'part-d', name: 'Part D', max: 2, desc: 'Correct justification or explanation.' },
                ],
                subSkills: [{ id: 'full', name: 'Full Response', desc: 'Answer all parts.', points: '0-9' }],
            },
            {
                id: 'no-calc-frq',
                name: 'No-Calculator FRQ (Part B)',
                points: 9,
                time: 30,
                desc: 'Multi-part question solved without a calculator. Must show all work and justification.',
                rubric: [
                    { id: 'part-a', name: 'Part A', max: 2, desc: 'Correct setup and answer.' },
                    { id: 'part-b', name: 'Part B', max: 3, desc: 'Correct method, including intermediate steps.' },
                    { id: 'part-c', name: 'Part C', max: 2, desc: 'Correct analysis or interpretation.' },
                    { id: 'part-d', name: 'Part D', max: 2, desc: 'Correct justification using calculus concepts.' },
                ],
                subSkills: [{ id: 'full', name: 'Full Response', desc: 'Answer all parts.', points: '0-9' }],
            },
        ],

        /* ── AP Statistics ──────────────────────────── */
        'math-stats': [
            {
                id: 'standard-frq',
                name: 'Standard FRQ',
                points: 4,
                time: 13,
                desc: 'Multi-part question scored using E/P/I (Essentially Correct, Partially Correct, Incorrect) per part.',
                rubric: [
                    { id: 'part-a', name: 'Part A', max: 1, desc: 'E = meets all components. P = meets some. I = fails to meet.' },
                    { id: 'part-b', name: 'Part B', max: 1, desc: 'E/P/I scoring based on statistical reasoning.' },
                    { id: 'part-c', name: 'Part C', max: 1, desc: 'E/P/I scoring based on interpretation.' },
                    { id: 'composite', name: 'Composite Score', max: 1, desc: 'Mapped from E/P/I pattern to 0-4 integer.' },
                ],
                subSkills: [{ id: 'full', name: 'Full Response', desc: 'Answer all parts.', points: '0-4' }],
            },
            {
                id: 'investigative',
                name: 'Investigative Task',
                points: 4,
                time: 25,
                desc: 'Extended multi-part question requiring deeper statistical investigation and analysis.',
                rubric: [
                    { id: 'part-a', name: 'Part A', max: 1, desc: 'Correct statistical identification or description.' },
                    { id: 'part-b', name: 'Part B', max: 1, desc: 'Correct analysis or computation.' },
                    { id: 'part-c', name: 'Part C', max: 1, desc: 'Valid interpretation and conclusion.' },
                    { id: 'part-d', name: 'Part D', max: 1, desc: 'Justified recommendation or extended analysis.' },
                ],
                subSkills: [{ id: 'full', name: 'Full Response', desc: 'Answer all parts.', points: '0-4' }],
            },
        ],

        /* ── AP Environmental Science ───────────────── */
        'science-enviro': [
            {
                id: 'calculation-frq',
                name: 'FRQ with Calculations',
                points: 10,
                time: 22,
                desc: 'Multi-part question with math calculations related to environmental data.',
                rubric: [
                    { id: 'identify', name: 'Identify/Describe', max: 3, desc: 'Correctly identifies environmental concepts or data.' },
                    { id: 'calculate', name: 'Calculations', max: 4, desc: 'Correct setup, math, and units.' },
                    { id: 'explain', name: 'Explain/Propose', max: 3, desc: 'Explains significance or proposes solutions.' },
                ],
                subSkills: [{ id: 'full', name: 'Full Response', desc: 'Answer all parts.', points: '0-10' }],
            },
            {
                id: 'design-investigation',
                name: 'Design an Investigation',
                points: 10,
                time: 22,
                desc: 'Design an experiment or investigation to test an environmental hypothesis.',
                rubric: [
                    { id: 'hypothesis', name: 'Hypothesis/Variables', max: 3, desc: 'Clear hypothesis with identified variables.' },
                    { id: 'procedure', name: 'Procedure', max: 4, desc: 'Logical, detailed procedure with controls.' },
                    { id: 'analysis', name: 'Data Analysis & Conclusion', max: 3, desc: 'Correct analysis approach and valid conclusions.' },
                ],
                subSkills: [{ id: 'full', name: 'Full Response', desc: 'Answer all parts.', points: '0-10' }],
            },
            {
                id: 'analyze-problem',
                name: 'Analyze an Environmental Problem',
                points: 10,
                time: 22,
                desc: 'Analyze an environmental issue, identify causes, and propose evidence-based solutions.',
                rubric: [
                    { id: 'identify', name: 'Identify Problem', max: 3, desc: 'Identifies the environmental problem and causes.' },
                    { id: 'analyze', name: 'Analyze Impact', max: 4, desc: 'Analyzes ecological and human impacts.' },
                    { id: 'propose', name: 'Propose Solutions', max: 3, desc: 'Proposes evidence-based solutions with trade-offs.' },
                ],
                subSkills: [{ id: 'full', name: 'Full Response', desc: 'Answer all parts.', points: '0-10' }],
            },
        ],

        /* ── AP Psychology ──────────────────────────── */
        psychology: [
            {
                id: 'article-analysis',
                name: 'Article Analysis Question (AAQ)',
                points: 7,
                time: 25,
                desc: 'Analyze a research article by identifying methods, variables, statistics, and applying psychological concepts.',
                rubric: [
                    { id: 'method', name: 'Research Method', max: 1, desc: 'Accurately identifies the research method used.' },
                    { id: 'variable', name: 'Research Variable', max: 1, desc: 'States a measurable operational definition.' },
                    { id: 'statistic', name: 'Statistic Interpretation', max: 1, desc: 'Accurately interprets what the statistics indicate.' },
                    { id: 'concept-1', name: 'Concept Application 1', max: 1, desc: 'Correctly applies a psychological concept to the study.' },
                    { id: 'concept-2', name: 'Concept Application 2', max: 1, desc: 'Correctly applies a second concept.' },
                    { id: 'ethical', name: 'Ethical Consideration', max: 1, desc: 'Identifies an ethical issue or guideline relevant to the study.' },
                    { id: 'limitation', name: 'Limitation/Extension', max: 1, desc: 'Identifies a limitation or proposes a valid extension.' },
                ],
                subSkills: [{ id: 'full', name: 'Full Response', desc: 'Answer all parts.', points: '0-7' }],
            },
        ],

        /* ── AP Computer Science A ──────────────────── */
        cs: [
            {
                id: 'code-writing',
                name: 'Code Writing FRQ',
                points: 9,
                time: 22,
                desc: 'Write Java code to solve a programming problem, implementing methods or classes.',
                rubric: [
                    { id: 'part-a', name: 'Part A', max: 4, desc: 'Correct method implementation with proper logic.' },
                    { id: 'part-b', name: 'Part B', max: 5, desc: 'Correct class/method with algorithm, no penalties.' },
                ],
                subSkills: [{ id: 'full', name: 'Full Response', desc: 'Write complete solution.', points: '0-9' }],
            },
        ],

        /* ── AP Human Geography ─────────────────────── */
        'human-geo': [
            {
                id: 'frq',
                name: 'FRQ',
                points: 7,
                time: 25,
                desc: 'Multi-part question requiring identification, description, explanation, and comparison of geographic concepts.',
                rubric: [
                    { id: 'part-a', name: 'Part A (Identify/Define)', max: 1, desc: 'Accurately identifies or defines a geographic concept.' },
                    { id: 'part-b', name: 'Part B (Describe)', max: 2, desc: 'Describes geographic patterns or processes.' },
                    { id: 'part-c', name: 'Part C (Explain)', max: 2, desc: 'Explains causes, effects, or relationships.' },
                    { id: 'part-d', name: 'Part D (Compare/Apply)', max: 2, desc: 'Compares concepts or applies to a new context.' },
                ],
                subSkills: [{ id: 'full', name: 'Full Response', desc: 'Answer all parts.', points: '0-7' }],
            },
        ],
    };

    /* ======================================================================
       STATE
       ====================================================================== */

    var state = {
        step: 1,
        subject: null,
        subjectKey: '',
        units: [],
        selectedUnits: [],
        questionType: null,
        subSkill: 'full',
        promptId: null,
        promptData: null,
        resultId: null,
        timerRunning: false,
        timerSeconds: 0,
        timerInterval: null,
    };

    /* ======================================================================
       WIZARD NAVIGATION
       ====================================================================== */

    function goToStep(n) {
        state.step = n;
        // Update step indicators
        document.querySelectorAll('.wizard-step').forEach(function (el) {
            var s = parseInt(el.dataset.step);
            el.classList.remove('active', 'done');
            if (s === n) el.classList.add('active');
            else if (s < n) el.classList.add('done');
        });
        document.querySelectorAll('.wizard-connector').forEach(function (el, i) {
            el.classList.toggle('done', i < n - 1);
        });
        // Show/hide panels
        document.querySelectorAll('.wizard-panel').forEach(function (el) {
            el.classList.remove('active');
        });
        var panel = document.getElementById('step-' + n);
        if (panel) panel.classList.add('active');
        // Show past attempts only on step 1
        var pastSection = document.getElementById('past-attempts-section');
        if (pastSection) pastSection.style.display = (n === 1) ? '' : 'none';
    }

    /* ======================================================================
       STEP 1: SUBJECT SELECTION
       ====================================================================== */

    function renderSubjects() {
        var grid = document.getElementById('subject-grid');
        if (!grid) return;
        var html = '';
        for (var key in AP_SUBJECTS) {
            var s = AP_SUBJECTS[key];
            var types = AP_FRQ_TYPES[s.category];
            var typeCount = types ? types.length : 0;
            html += '<div class="subject-card" onclick="FRQ.selectSubject(\'' + key + '\')">' +
                '<div class="subj-icon ' + s.iconClass + '"><i class="fa-solid ' + s.icon + '"></i></div>' +
                '<div><div class="subj-name">' + s.name + '</div>' +
                '<div class="subj-types">' + typeCount + ' FRQ type' + (typeCount !== 1 ? 's' : '') + '</div></div></div>';
        }
        grid.innerHTML = html;
    }

    function selectSubject(key) {
        state.subjectKey = key;
        state.subject = AP_SUBJECTS[key];
        renderUnits();
        goToStep(2);
    }

    /* ======================================================================
       STEP 2: UNIT SELECTION
       ====================================================================== */

    function renderUnits() {
        var container = document.getElementById('unit-selection');
        if (!container) return;

        var units = getUnitsForSubject(state.subjectKey);
        state.units = units;
        state.selectedUnits = units.map(function (u) { return u.id; });

        var html = '<div class="unit-checkbox all-units" onclick="FRQ.toggleAllUnits(this)">' +
            '<input type="checkbox" checked id="all-units-cb"> <label for="all-units-cb">All Units</label></div>';

        units.forEach(function (u) {
            html += '<div class="unit-checkbox" onclick="FRQ.toggleUnit(this, \'' + u.id + '\')">' +
                '<input type="checkbox" checked data-unit="' + u.id + '"> <label>' + u.name + '</label></div>';
        });
        container.innerHTML = html;
    }

    function getUnitsForSubject(key) {
        var unitMaps = {
            'ap-us-history': [
                { id: '1', name: 'Unit 1: Period 1 (1491-1607)' }, { id: '2', name: 'Unit 2: Period 2 (1607-1754)' },
                { id: '3', name: 'Unit 3: Period 3 (1754-1800)' }, { id: '4', name: 'Unit 4: Period 4 (1800-1848)' },
                { id: '5', name: 'Unit 5: Period 5 (1844-1877)' }, { id: '6', name: 'Unit 6: Period 6 (1865-1898)' },
                { id: '7', name: 'Unit 7: Period 7 (1890-1945)' }, { id: '8', name: 'Unit 8: Period 8 (1945-1980)' },
                { id: '9', name: 'Unit 9: Period 9 (1980-Present)' },
            ],
            'ap-world-history': [
                { id: '1', name: 'Unit 1: The Global Tapestry (1200-1450)' }, { id: '2', name: 'Unit 2: Networks of Exchange (1200-1450)' },
                { id: '3', name: 'Unit 3: Land-Based Empires (1450-1750)' }, { id: '4', name: 'Unit 4: Transoceanic Interconnections (1450-1750)' },
                { id: '5', name: 'Unit 5: Revolutions (1750-1900)' }, { id: '6', name: 'Unit 6: Consequences of Industrialization (1750-1900)' },
                { id: '7', name: 'Unit 7: Global Conflict (1900-Present)' }, { id: '8', name: 'Unit 8: Cold War & Decolonization (1900-Present)' },
                { id: '9', name: 'Unit 9: Globalization (1900-Present)' },
            ],
            'ap-euro-history': [
                { id: '1', name: 'Unit 1: Renaissance & Exploration (1450-1648)' }, { id: '2', name: 'Unit 2: Age of Reformation (1450-1648)' },
                { id: '3', name: 'Unit 3: Absolutism & Constitutionalism (1648-1815)' }, { id: '4', name: 'Unit 4: Scientific, Philosophical, Political Dev. (1648-1815)' },
                { id: '5', name: 'Unit 5: Conflict, Crisis, Reaction (1648-1815)' }, { id: '6', name: 'Unit 6: Industrialization (1815-1914)' },
                { id: '7', name: 'Unit 7: 19th-Century Perspectives (1815-1914)' }, { id: '8', name: 'Unit 8: 20th-Century Global Conflicts (1914-Present)' },
                { id: '9', name: 'Unit 9: Cold War & Contemporary Europe (1914-Present)' },
            ],
            'ap-gov': [
                { id: '1', name: 'Unit 1: Foundations of American Democracy' }, { id: '2', name: 'Unit 2: Interactions Among Branches' },
                { id: '3', name: 'Unit 3: Civil Liberties & Civil Rights' }, { id: '4', name: 'Unit 4: American Political Ideologies & Beliefs' },
                { id: '5', name: 'Unit 5: Political Participation' },
            ],
            'ap-english-lang': [
                { id: '1', name: 'Unit 1: Claims, Evidence & Reasoning' }, { id: '2', name: 'Unit 2: Rhetorical Strategies & Style' },
                { id: '3', name: 'Unit 3: Synthesis & Argumentation' }, { id: '4', name: 'Unit 4: Rhetorical Situations' },
            ],
            'ap-english-lit': [
                { id: '1', name: 'Unit 1: Short Fiction' }, { id: '2', name: 'Unit 2: Poetry' },
                { id: '3', name: 'Unit 3: Longer Fiction or Drama' }, { id: '4', name: 'Unit 4: Literary Argument' },
            ],
            'ap-biology': [
                { id: '1', name: 'Unit 1: Chemistry of Life' }, { id: '2', name: 'Unit 2: Cell Structure & Function' },
                { id: '3', name: 'Unit 3: Cellular Energetics' }, { id: '4', name: 'Unit 4: Cell Communication & Cell Cycle' },
                { id: '5', name: 'Unit 5: Heredity' }, { id: '6', name: 'Unit 6: Gene Expression & Regulation' },
                { id: '7', name: 'Unit 7: Natural Selection' }, { id: '8', name: 'Unit 8: Ecology' },
            ],
            'ap-chemistry': [
                { id: '1', name: 'Unit 1: Atomic Structure & Properties' }, { id: '2', name: 'Unit 2: Molecular & Ionic Bonding' },
                { id: '3', name: 'Unit 3: Intermolecular Forces' }, { id: '4', name: 'Unit 4: Chemical Reactions' },
                { id: '5', name: 'Unit 5: Kinetics' }, { id: '6', name: 'Unit 6: Thermodynamics' },
                { id: '7', name: 'Unit 7: Equilibrium' }, { id: '8', name: 'Unit 8: Acids & Bases' },
                { id: '9', name: 'Unit 9: Applications of Thermodynamics' },
            ],
            'ap-physics-1': [
                { id: '1', name: 'Unit 1: Kinematics' }, { id: '2', name: 'Unit 2: Dynamics' },
                { id: '3', name: 'Unit 3: Circular Motion & Gravitation' }, { id: '4', name: 'Unit 4: Energy' },
                { id: '5', name: 'Unit 5: Momentum' }, { id: '6', name: 'Unit 6: Simple Harmonic Motion' },
                { id: '7', name: 'Unit 7: Torque & Rotational Motion' },
            ],
            'ap-physics-2': [
                { id: '1', name: 'Unit 1: Fluids' }, { id: '2', name: 'Unit 2: Thermodynamics' },
                { id: '3', name: 'Unit 3: Electric Force, Field, Potential' }, { id: '4', name: 'Unit 4: Electric Circuits' },
                { id: '5', name: 'Unit 5: Magnetism & EM Induction' }, { id: '6', name: 'Unit 6: Geometric & Physical Optics' },
                { id: '7', name: 'Unit 7: Quantum, Atomic, Nuclear Physics' },
            ],
            'ap-physics-c-mech': [
                { id: '1', name: 'Unit 1: Kinematics' }, { id: '2', name: 'Unit 2: Newton\'s Laws' },
                { id: '3', name: 'Unit 3: Work, Energy, Power' }, { id: '4', name: 'Unit 4: Systems of Particles & Linear Momentum' },
                { id: '5', name: 'Unit 5: Rotation' }, { id: '6', name: 'Unit 6: Oscillations' }, { id: '7', name: 'Unit 7: Gravitation' },
            ],
            'ap-physics-c-em': [
                { id: '1', name: 'Unit 1: Electrostatics' }, { id: '2', name: 'Unit 2: Conductors, Capacitors, Dielectrics' },
                { id: '3', name: 'Unit 3: Electric Circuits' }, { id: '4', name: 'Unit 4: Magnetic Fields' },
                { id: '5', name: 'Unit 5: Electromagnetism' },
            ],
            'ap-calculus-ab': [
                { id: '1', name: 'Unit 1: Limits & Continuity' }, { id: '2', name: 'Unit 2: Differentiation: Definition & Fundamental Properties' },
                { id: '3', name: 'Unit 3: Differentiation: Composite, Implicit, Inverse' }, { id: '4', name: 'Unit 4: Contextual Applications of Differentiation' },
                { id: '5', name: 'Unit 5: Analytical Applications of Differentiation' }, { id: '6', name: 'Unit 6: Integration & Accumulation of Change' },
                { id: '7', name: 'Unit 7: Differential Equations' }, { id: '8', name: 'Unit 8: Applications of Integration' },
            ],
            'ap-calculus-bc': [
                { id: '1', name: 'Unit 1: Limits & Continuity' }, { id: '2', name: 'Unit 2: Differentiation: Basics' },
                { id: '3', name: 'Unit 3: Differentiation: Composite, Implicit, Inverse' }, { id: '4', name: 'Unit 4: Contextual Applications' },
                { id: '5', name: 'Unit 5: Analytical Applications' }, { id: '6', name: 'Unit 6: Integration' },
                { id: '7', name: 'Unit 7: Differential Equations' }, { id: '8', name: 'Unit 8: Applications of Integration' },
                { id: '9', name: 'Unit 9: Parametric, Polar, Vector Functions' }, { id: '10', name: 'Unit 10: Infinite Sequences & Series' },
            ],
            'ap-statistics': [
                { id: '1', name: 'Unit 1: Exploring One-Variable Data' }, { id: '2', name: 'Unit 2: Exploring Two-Variable Data' },
                { id: '3', name: 'Unit 3: Collecting Data' }, { id: '4', name: 'Unit 4: Probability, Random Variables, Distributions' },
                { id: '5', name: 'Unit 5: Sampling Distributions' }, { id: '6', name: 'Unit 6: Inference for Categorical Data: Proportions' },
                { id: '7', name: 'Unit 7: Inference for Quantitative Data: Means' }, { id: '8', name: 'Unit 8: Inference for Categorical Data: Chi-Square' },
                { id: '9', name: 'Unit 9: Inference for Quantitative Data: Slopes' },
            ],
            'ap-environmental': [
                { id: '1', name: 'Unit 1: The Living World: Ecosystems' }, { id: '2', name: 'Unit 2: The Living World: Biodiversity' },
                { id: '3', name: 'Unit 3: Populations' }, { id: '4', name: 'Unit 4: Earth Systems & Resources' },
                { id: '5', name: 'Unit 5: Land & Water Use' }, { id: '6', name: 'Unit 6: Energy Resources & Consumption' },
                { id: '7', name: 'Unit 7: Atmospheric Pollution' }, { id: '8', name: 'Unit 8: Aquatic & Terrestrial Pollution' },
                { id: '9', name: 'Unit 9: Global Change' },
            ],
            'ap-psychology': [
                { id: '1', name: 'Unit 1: Scientific Foundations of Psychology' }, { id: '2', name: 'Unit 2: Biological Bases of Behavior' },
                { id: '3', name: 'Unit 3: Sensation & Perception' }, { id: '4', name: 'Unit 4: Learning' },
                { id: '5', name: 'Unit 5: Cognitive Psychology' }, { id: '6', name: 'Unit 6: Developmental Psychology' },
                { id: '7', name: 'Unit 7: Motivation, Emotion, Personality' }, { id: '8', name: 'Unit 8: Clinical Psychology' },
                { id: '9', name: 'Unit 9: Social Psychology' },
            ],
            'ap-cs-a': [
                { id: '1', name: 'Unit 1: Primitive Types' }, { id: '2', name: 'Unit 2: Using Objects' },
                { id: '3', name: 'Unit 3: Boolean Expressions & if Statements' }, { id: '4', name: 'Unit 4: Iteration' },
                { id: '5', name: 'Unit 5: Writing Classes' }, { id: '6', name: 'Unit 6: Array' },
                { id: '7', name: 'Unit 7: ArrayList' }, { id: '8', name: 'Unit 8: 2D Array' },
                { id: '9', name: 'Unit 9: Inheritance' }, { id: '10', name: 'Unit 10: Recursion' },
            ],
            'ap-human-geo': [
                { id: '1', name: 'Unit 1: Thinking Geographically' }, { id: '2', name: 'Unit 2: Population & Migration Patterns' },
                { id: '3', name: 'Unit 3: Cultural Patterns & Processes' }, { id: '4', name: 'Unit 4: Political Patterns & Processes' },
                { id: '5', name: 'Unit 5: Agriculture & Rural Land-Use' }, { id: '6', name: 'Unit 6: Cities & Urban Land-Use' },
                { id: '7', name: 'Unit 7: Industrial & Economic Development' },
            ],
        };
        return unitMaps[key] || [{ id: 'all', name: 'All Topics' }];
    }

    function toggleAllUnits(el) {
        var cb = el.querySelector('input');
        cb.checked = !cb.checked;
        var checked = cb.checked;
        state.selectedUnits = checked ? state.units.map(function (u) { return u.id; }) : [];
        document.querySelectorAll('.unit-checkbox:not(.all-units) input').forEach(function (inp) {
            inp.checked = checked;
        });
    }

    function toggleUnit(el, unitId) {
        var cb = el.querySelector('input');
        cb.checked = !cb.checked;
        if (cb.checked) {
            if (state.selectedUnits.indexOf(unitId) === -1) state.selectedUnits.push(unitId);
        } else {
            state.selectedUnits = state.selectedUnits.filter(function (u) { return u !== unitId; });
        }
        var allCb = document.querySelector('.all-units input');
        if (allCb) allCb.checked = state.selectedUnits.length === state.units.length;
    }

    function confirmUnits() {
        if (state.selectedUnits.length === 0) {
            showToast('Please select at least one unit.');
            return;
        }
        renderQuestionTypes();
        goToStep(3);
    }

    /* ======================================================================
       STEP 3: QUESTION TYPE SELECTION
       ====================================================================== */

    function renderQuestionTypes() {
        var grid = document.getElementById('qtype-grid');
        if (!grid) return;
        var types = AP_FRQ_TYPES[state.subject.category] || [];
        var html = '';
        types.forEach(function (t) {
            html += '<div class="qtype-card" onclick="FRQ.selectType(\'' + t.id + '\')">' +
                '<div class="qt-name">' + esc(t.name) + ' <span class="qt-points">' + t.points + ' pts</span></div>' +
                '<div class="qt-desc">' + esc(t.desc) + '</div>' +
                '<div class="qt-time"><i class="fa-solid fa-clock"></i> ~' + t.time + ' min recommended</div></div>';
        });
        grid.innerHTML = html;
    }

    function selectType(typeId) {
        var types = AP_FRQ_TYPES[state.subject.category] || [];
        state.questionType = types.find(function (t) { return t.id === typeId; }) || null;
        if (!state.questionType) return;

        // Skip step 4 entirely if there's only one sub-skill option (SAQs, science FRQs, CS, etc.)
        if (!state.questionType.subSkills || state.questionType.subSkills.length <= 1) {
            state.subSkill = 'full';
            goToStep(4); // still mark step 4 as visited for the wizard indicator
            // Auto-trigger generation
            generatePrompt();
            return;
        }

        renderFocusOptions();
        goToStep(4);
    }

    /* ======================================================================
       STEP 4: SUB-SKILL / FOCUS MODE
       ====================================================================== */

    function renderFocusOptions() {
        var container = document.getElementById('focus-options');
        if (!container || !state.questionType) return;
        var skills = state.questionType.subSkills || [];
        state.subSkill = 'full';
        var html = '';
        skills.forEach(function (sk, i) {
            var checked = sk.id === 'full' ? ' checked' : '';
            var selected = sk.id === 'full' ? ' selected' : '';
            html += '<div class="focus-option' + selected + '" onclick="FRQ.selectFocus(\'' + sk.id + '\', this)">' +
                '<input type="radio" name="focus-mode" value="' + sk.id + '"' + checked + '>' +
                '<div class="fo-text"><div class="fo-name">' + esc(sk.name) + '</div>' +
                '<div class="fo-desc">' + esc(sk.desc) + '</div>' +
                '<span class="fo-points">' + sk.points + '</span></div></div>';
        });
        container.innerHTML = html;
    }

    function selectFocus(skillId, el) {
        state.subSkill = skillId;
        document.querySelectorAll('.focus-option').forEach(function (o) { o.classList.remove('selected'); });
        if (el) el.classList.add('selected');
        var radio = el ? el.querySelector('input') : null;
        if (radio) radio.checked = true;
    }

    /* ======================================================================
       STEP 5: GENERATE PROMPT + WRITING INTERFACE
       ====================================================================== */

    function _showPromptSkeleton() {
        var meta = document.getElementById('prompt-meta');
        if (meta) meta.innerHTML = '<div class="skeleton skeleton-text" style="width:180px;height:12px;"></div>';
        var body = document.getElementById('prompt-body');
        if (body) body.innerHTML =
            '<div class="skeleton skeleton-text lg" style="width:80%;margin-bottom:16px;"></div>' +
            '<div class="skeleton skeleton-text" style="width:100%;"></div>' +
            '<div class="skeleton skeleton-text" style="width:95%;"></div>' +
            '<div class="skeleton skeleton-text" style="width:88%;"></div>' +
            '<div class="skeleton skeleton-text" style="width:70%;margin-bottom:20px;"></div>' +
            '<div class="skeleton skeleton-text" style="width:100%;"></div>' +
            '<div class="skeleton skeleton-text" style="width:92%;"></div>' +
            '<div class="skeleton skeleton-text" style="width:60%;"></div>';
        var docsContainer = document.getElementById('prompt-documents');
        if (docsContainer) docsContainer.style.display = 'none';
        var refBtn = document.getElementById('ref-toggle-btn');
        if (refBtn) refBtn.style.display = 'none';
        var textarea = document.getElementById('response-textarea');
        if (textarea) { textarea.value = ''; textarea.disabled = true; textarea.placeholder = 'Generating your prompt...'; }
        var submitBtn = document.getElementById('submit-response-btn');
        if (submitBtn) submitBtn.disabled = true;
    }

    async function generatePrompt() {
        var btn = document.getElementById('generate-btn');
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Generating...';

        // Show skeleton immediately and navigate to writing step
        _showPromptSkeleton();
        goToStep(5);

        try {
            var selectedUnitNames = state.selectedUnits.map(function (uid) {
                var u = state.units.find(function (unit) { return unit.id === uid; });
                return u ? u.name : uid;
            });

            var resp = await fetch('/api/frq-generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    subject: state.subjectKey,
                    subjectName: state.subject.name,
                    category: state.subject.category,
                    units: selectedUnitNames,
                    questionType: state.questionType.id,
                    questionTypeName: state.questionType.name,
                    subSkill: state.subSkill,
                    rubric: state.questionType.rubric,
                    maxPoints: state.questionType.points,
                    timerMinutes: state.questionType.time,
                }),
            });
            var data = await resp.json();
            if (data.error) throw new Error(data.error);

            state.promptId = data.promptId;
            state.promptData = data;
            renderWritingInterface(data);
        } catch (e) {
            showToast('Failed to generate FRQ: ' + e.message);
            goToStep(4);
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Generate FRQ';
        }
    }

    function renderWritingInterface(data) {
        // Prompt meta
        var meta = document.getElementById('prompt-meta');
        if (meta) {
            meta.innerHTML = '<span>' + esc(state.subject.shortName) + '</span><span>|</span><span>' +
                esc(state.questionType.name) + '</span><span>|</span><span>' +
                state.questionType.points + ' pts</span>';
        }

        // Prompt body -- include instructions, passage, article, and data description
        var body = document.getElementById('prompt-body');
        if (body) {
            var promptHtml = formatPromptText(data.prompt || '');
            if (data.instructions) {
                promptHtml += '<div style="margin-top:14px;padding:12px 16px;background:var(--color-primary-light);border-radius:var(--radius-sm);font-size:0.85rem;">' +
                    '<strong><i class="fa-solid fa-info-circle" style="color:var(--color-primary);margin-right:6px;"></i>Instructions:</strong> ' +
                    esc(data.instructions) + '</div>';
            }
            if (data.passage) {
                promptHtml += '<div style="margin-top:16px;padding:16px;background:var(--color-bg);border-left:3px solid var(--color-primary);border-radius:var(--radius-sm);font-size:0.88rem;line-height:1.8;">' +
                    formatPromptText(data.passage) + '</div>';
            }
            if (data.article) {
                promptHtml += '<div style="margin-top:16px;padding:16px;background:var(--color-bg);border-left:3px solid var(--color-primary);border-radius:var(--radius-sm);font-size:0.88rem;line-height:1.8;">' +
                    '<div style="font-weight:700;margin-bottom:8px;"><i class="fa-solid fa-newspaper" style="color:var(--color-primary);margin-right:6px;"></i>Article</div>' +
                    formatPromptText(data.article) + '</div>';
            }
            if (data.dataDescription) {
                promptHtml += '<div style="margin-top:16px;padding:16px;background:var(--color-bg);border-left:3px solid var(--color-primary);border-radius:var(--radius-sm);font-size:0.88rem;line-height:1.8;">' +
                    '<div style="font-weight:700;margin-bottom:8px;"><i class="fa-solid fa-chart-simple" style="color:var(--color-primary);margin-right:6px;"></i>Data</div>' +
                    formatPromptText(data.dataDescription) + '</div>';
            }
            body.innerHTML = promptHtml;
        }

        // Documents / Sources
        var docsContainer = document.getElementById('prompt-documents');
        var docsList = document.getElementById('documents-list');
        if (docsContainer && docsList) {
            if (data.documents && data.documents.length > 0) {
                docsContainer.style.display = '';
                var docsHtml = '';
                data.documents.forEach(function (doc, i) {
                    docsHtml += '<div class="doc-item"><div class="doc-source">Document ' + (i + 1) + ': ' +
                        esc(doc.source || '') + '</div><div class="doc-content">' +
                        formatPromptText(doc.content || '') + '</div></div>';
                });
                docsList.innerHTML = docsHtml;
            } else {
                docsContainer.style.display = 'none';
            }
        }

        // Reference material
        var refBtn = document.getElementById('ref-toggle-btn');
        var refContent = document.getElementById('reference-content');
        if (refBtn && refContent) {
            if (data.referenceSheet) {
                refBtn.style.display = '';
                refContent.innerHTML = '<pre>' + esc(data.referenceSheet) + '</pre>';
            } else {
                refBtn.style.display = 'none';
            }
        }

        // Reset response area
        var textarea = document.getElementById('response-textarea');
        if (textarea) { textarea.value = ''; textarea.disabled = false; textarea.placeholder = 'Write your response here...'; }
        updateWordCount();

        // Reset timer
        resetTimer(data.timerMinutes || state.questionType.time);

        // Enable submit
        var submitBtn = document.getElementById('submit-response-btn');
        if (submitBtn) { submitBtn.disabled = false; submitBtn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Submit for Grading'; }
    }

    function formatPromptText(text) {
        if (!text) return '';
        return text.split('\n').map(function (line) {
            return '<p>' + esc(line) + '</p>';
        }).join('');
    }

    function toggleReference() {
        var panel = document.getElementById('reference-panel');
        if (panel) panel.style.display = panel.style.display === 'none' ? '' : 'none';
    }

    /* ── Word / Paragraph Count ──────────────────── */
    function updateWordCount() {
        var textarea = document.getElementById('response-textarea');
        if (!textarea) return;
        var text = textarea.value.trim();
        var words = text ? text.split(/\s+/).length : 0;
        var paras = text ? text.split(/\n\s*\n/).filter(function (p) { return p.trim(); }).length : 0;
        if (paras < 1 && words > 0) paras = 1;
        var wc = document.getElementById('word-count');
        var pc = document.getElementById('para-count');
        if (wc) wc.textContent = words + ' word' + (words !== 1 ? 's' : '');
        if (pc) pc.textContent = paras + ' paragraph' + (paras !== 1 ? 's' : '');
    }

    /* ── Timer ───────────────────────────────────── */
    function resetTimer(minutes) {
        stopTimer();
        state.timerSeconds = 0;
        state.timerRunning = false;
        var display = document.getElementById('timer-display');
        if (display) display.textContent = '00:00';
        var btn = document.getElementById('timer-btn');
        if (btn) btn.innerHTML = '<i class="fa-solid fa-play"></i>';
        var wrap = document.getElementById('timer-wrap');
        if (wrap) wrap.title = 'Recommended: ~' + minutes + ' min';
    }

    function toggleTimer() {
        if (state.timerRunning) {
            stopTimer();
        } else {
            startTimer();
        }
    }

    function startTimer() {
        state.timerRunning = true;
        var btn = document.getElementById('timer-btn');
        if (btn) btn.innerHTML = '<i class="fa-solid fa-pause"></i>';
        state.timerInterval = setInterval(function () {
            state.timerSeconds++;
            var m = Math.floor(state.timerSeconds / 60);
            var s = state.timerSeconds % 60;
            var display = document.getElementById('timer-display');
            if (display) display.textContent = String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
        }, 1000);
    }

    function stopTimer() {
        state.timerRunning = false;
        if (state.timerInterval) { clearInterval(state.timerInterval); state.timerInterval = null; }
        var btn = document.getElementById('timer-btn');
        if (btn) btn.innerHTML = '<i class="fa-solid fa-play"></i>';
    }

    /* ======================================================================
       STEP 6: SUBMIT + GRADING FEEDBACK
       ====================================================================== */

    async function submitResponse() {
        var textarea = document.getElementById('response-textarea');
        var response = textarea ? textarea.value.trim() : '';
        if (!response) {
            showToast('Please write a response before submitting.');
            return;
        }
        if (response.length < 20) {
            showToast('Your response seems too short. Please write more before submitting.');
            return;
        }

        stopTimer();

        var btn = document.getElementById('submit-response-btn');
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Submitting...';
        textarea.disabled = true;

        // Show grading step
        goToStep(6);
        document.getElementById('grading-loading').style.display = '';
        document.getElementById('results-content').style.display = 'none';

        try {
            var resp = await fetch('/api/frq-grade', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    promptId: state.promptId,
                    studentResponse: response,
                    userId: localStorage.getItem('alphalearn_sourcedId') || '',
                    subject: state.subjectKey,
                    subjectName: state.subject.name,
                    category: state.subject.category,
                    questionType: state.questionType.id,
                    questionTypeName: state.questionType.name,
                    subSkill: state.subSkill,
                    rubric: state.questionType.rubric,
                    maxPoints: state.questionType.points,
                    timerSeconds: state.timerSeconds,
                }),
            });
            var data = await resp.json();
            if (data.error) throw new Error(data.error);

            state.resultId = data.resultId;
            pollGradingStatus(data.resultId);
        } catch (e) {
            showToast('Failed to submit: ' + e.message);
            document.getElementById('grading-loading').style.display = 'none';
            goToStep(5);
            btn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Submit for Grading';
            textarea.disabled = false;
        }
    }

    async function pollGradingStatus(resultId) {
        var maxAttempts = 60;
        var attempt = 0;
        var pollInterval = 2000;

        var poll = async function () {
            attempt++;
            try {
                var resp = await fetch('/api/frq-grade-status?resultId=' + encodeURIComponent(resultId));
                var data = await resp.json();

                if (data.status === 'complete' && data.result) {
                    renderResults(data.result);
                    return;
                }
                if (data.status === 'error') {
                    showToast('Grading failed: ' + (data.error || 'Unknown error'));
                    goToStep(5);
                    return;
                }
            } catch (e) {
                // Network error, keep trying
            }

            if (attempt < maxAttempts) {
                setTimeout(poll, pollInterval);
                if (attempt > 10) pollInterval = 4000;
            } else {
                showToast('Grading is taking too long. Please try again.');
                goToStep(5);
            }
        };
        poll();
    }

    function renderResults(result) {
        document.getElementById('grading-loading').style.display = 'none';
        document.getElementById('results-content').style.display = '';

        // Score overview
        var scoreOverview = document.getElementById('score-overview');
        var total = result.totalScore || 0;
        var max = result.maxScore || state.questionType.points;
        var pct = max > 0 ? Math.round((total / max) * 100) : 0;
        scoreOverview.innerHTML = '<div class="score-big">' + total + '/' + max + '</div>' +
            '<div class="score-label">' + esc(state.questionType.name) + ' &mdash; ' + esc(state.subject.shortName) + '</div>' +
            '<div class="score-bar-wrap"><div class="score-bar-fill" style="width:' + pct + '%"></div></div>';

        // Rubric row feedback
        var rubricFeedback = document.getElementById('rubric-feedback');
        var rowsHtml = '';
        var rows = result.rubricRows || [];
        rows.forEach(function (row) {
            var status = row.earned >= row.max ? 'earned' : (row.earned > 0 ? 'partial' : 'missed');
            var icon = status === 'earned' ? 'fa-check-circle' : (status === 'partial' ? 'fa-minus-circle' : 'fa-times-circle');
            rowsHtml += '<div class="rubric-row-card ' + status + '">' +
                '<div class="rr-header"><span class="rr-name">' + esc(row.name) + '</span>' +
                '<span class="rr-score ' + status + '"><i class="fa-solid ' + icon + '"></i> ' + row.earned + '/' + row.max + '</span></div>' +
                '<div class="rr-feedback">' + formatFeedback(row.feedback) + '</div>';
            if (row.excerpts && row.excerpts.length > 0) {
                row.excerpts.forEach(function (ex) {
                    rowsHtml += '<div class="rr-excerpt">"' + esc(ex) + '"</div>';
                });
            }
            rowsHtml += '</div>';
        });
        rubricFeedback.innerHTML = rowsHtml;

        // Overall feedback
        var overallFeedback = document.getElementById('overall-feedback');
        var ofHtml = '<h3><i class="fa-solid fa-message"></i> Overall Feedback</h3>';
        if (result.overallFeedback) {
            ofHtml += '<div class="overall-text">' + formatFeedback(result.overallFeedback) + '</div>';
        }
        if (result.strengths && result.strengths.length > 0) {
            ofHtml += '<div class="feedback-section"><h4><i class="fa-solid fa-star strength-icon"></i> Strengths</h4><ul>';
            result.strengths.forEach(function (s) { ofHtml += '<li>' + esc(s) + '</li>'; });
            ofHtml += '</ul></div>';
        }
        if (result.improvements && result.improvements.length > 0) {
            ofHtml += '<div class="feedback-section"><h4><i class="fa-solid fa-lightbulb improve-icon"></i> Areas to Improve</h4><ul>';
            result.improvements.forEach(function (s) { ofHtml += '<li>' + esc(s) + '</li>'; });
            ofHtml += '</ul></div>';
        }
        overallFeedback.innerHTML = ofHtml;
    }

    function formatFeedback(text) {
        if (!text) return '';
        return text.split('\n').filter(function (l) { return l.trim(); })
            .map(function (l) { return '<p>' + esc(l) + '</p>'; }).join('');
    }

    /* ── Navigation helpers ──────────────────────── */
    function goBackFromWrite() {
        // If step 4 was skipped (only 1 sub-skill), go back to step 3
        if (!state.questionType || !state.questionType.subSkills || state.questionType.subSkills.length <= 1) {
            goToStep(3);
        } else {
            goToStep(4);
        }
    }

    /* ── Try Again / New FRQ ─────────────────────── */
    function tryAgain() {
        goToStep(5);
        var textarea = document.getElementById('response-textarea');
        if (textarea) { textarea.value = ''; textarea.disabled = false; }
        updateWordCount();
        resetTimer(state.questionType ? state.questionType.time : 40);
        var submitBtn = document.getElementById('submit-response-btn');
        if (submitBtn) { submitBtn.disabled = false; submitBtn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Submit for Grading'; }
    }

    function newFRQ() {
        state.promptId = null;
        state.promptData = null;
        state.resultId = null;
        goToStep(1);
    }

    /* ======================================================================
       PAST ATTEMPTS
       ====================================================================== */

    async function loadPastAttempts() {
        var userId = localStorage.getItem('alphalearn_sourcedId') || '';
        if (!userId) return;
        try {
            var resp = await fetch('/api/frq-history?userId=' + encodeURIComponent(userId));
            var data = await resp.json();
            if (data.attempts && data.attempts.length > 0) {
                renderPastAttempts(data.attempts);
            }
        } catch (e) {
            // Silent fail
        }
    }

    function renderPastAttempts(attempts) {
        var section = document.getElementById('past-attempts-section');
        var grid = document.getElementById('attempts-grid');
        if (!section || !grid) return;

        section.style.display = '';
        var html = '';
        attempts.forEach(function (a) {
            var pct = a.maxScore > 0 ? Math.round((a.totalScore / a.maxScore) * 100) : 0;
            var pillClass = pct >= 70 ? 'good' : (pct >= 40 ? 'ok' : 'low');
            var date = a.date ? new Date(a.date).toLocaleDateString() : '';
            html += '<div class="attempt-card">' +
                '<div class="ac-type">' + esc(a.questionType || '') + '</div>' +
                '<div class="ac-subject">' + esc(a.subjectName || '') + '</div>' +
                '<div class="ac-score">Score: <span class="score-pill ' + pillClass + '">' + a.totalScore + '/' + a.maxScore + '</span></div>' +
                '<div class="ac-date">' + esc(date) + '</div></div>';
        });
        grid.innerHTML = html;
    }

    /* ======================================================================
       UTILITIES
       ====================================================================== */

    function esc(s) {
        if (!s) return '';
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function showToast(msg) {
        var toast = document.getElementById('toast');
        if (!toast) return;
        toast.textContent = msg;
        toast.classList.add('show');
        setTimeout(function () { toast.classList.remove('show'); }, 3000);
    }

    /* ======================================================================
       INIT
       ====================================================================== */

    function init() {
        renderSubjects();
        loadPastAttempts();

        // Attach word count listener
        var textarea = document.getElementById('response-textarea');
        if (textarea) {
            textarea.addEventListener('input', updateWordCount);
        }
    }

    // Run on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Expose public API
    window.FRQ = {
        goToStep: goToStep,
        goBackFromWrite: goBackFromWrite,
        selectSubject: selectSubject,
        toggleAllUnits: toggleAllUnits,
        toggleUnit: toggleUnit,
        confirmUnits: confirmUnits,
        selectType: selectType,
        selectFocus: selectFocus,
        generatePrompt: generatePrompt,
        toggleReference: toggleReference,
        toggleTimer: toggleTimer,
        submitResponse: submitResponse,
        tryAgain: tryAgain,
        newFRQ: newFRQ,
    };

})();
