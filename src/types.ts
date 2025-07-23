import { z } from 'zod';
import type { ZodRawShape, ZodTypeAny } from 'zod';
import type { ToolAnnotations } from '@modelcontextprotocol/sdk/types.js';
import { Router } from 'express';
import type { Pool } from 'pg';

export type ToolConfig<
  InputArgs extends ZodRawShape,
  OutputArgs extends ZodRawShape,
> = {
  title?: string;
  description?: string;
  inputSchema: InputArgs;
  outputSchema: OutputArgs;
  annotations?: ToolAnnotations;
};

export interface ApiDefinition<
  InputArgs extends ZodRawShape,
  OutputArgs extends ZodRawShape,
  SimplifiedOutputArgs = OutputArgs,
> {
  name: string;
  method?: 'get' | 'post' | 'put' | 'delete';
  route?: string;
  config: ToolConfig<InputArgs, OutputArgs>;
  fn: (
    args: z.objectOutputType<InputArgs, ZodTypeAny>,
  ) => Promise<z.objectOutputType<OutputArgs, ZodTypeAny>>;
  // workaround for the fact that OutputArgs can't be an array
  pickResult?: (
    result: z.objectOutputType<OutputArgs, ZodTypeAny>,
  ) => SimplifiedOutputArgs;
}

export interface ServerContext {
  pgPool: Pool;
}

export type ApiFactory<I extends ZodRawShape, O extends ZodRawShape, S = O> = (
  ctx: ServerContext,
) => ApiDefinition<I, O, S>;

/**
 * RouterFactory returns an Express Router and a cleanup function.
 */
export type RouterFactoryResult = [Router, () => void | Promise<void>];
export type RouterFactory = (ctx: ServerContext) => RouterFactoryResult;
