/**
 * Chamadas do Modo Carreira (`/api/v1/career`, 002 interfaces/career.md) pelo cliente orval,
 * com as respostas validadas pelos schemas zod gerados. Injetável nos testes (`CareerApi`).
 */
import {
  acceptOrderApiV1CareerProfilesProfileIdJobsPost,
  getProfileApiV1CareerProfilesProfileIdGet,
  listJobsApiV1CareerProfilesProfileIdJobsGet,
  listOrdersApiV1CareerOrdersGet,
  settleJobApiV1CareerJobsJobIdSettlePost,
} from "@/lib/api/generated/career/career";
import {
  AcceptOrderApiV1CareerProfilesProfileIdJobsPostResponse,
  GetProfileApiV1CareerProfilesProfileIdGetResponse,
  ListJobsApiV1CareerProfilesProfileIdJobsGetResponse,
  ListOrdersApiV1CareerOrdersGetResponse,
  SettleJobApiV1CareerJobsJobIdSettlePostResponse,
} from "@/lib/api/generated/zod/career/career";

import type { CareerJob, CareerProfile, WorkOrder } from "./types";

export interface CareerApi {
  getProfile(profileId: string): Promise<CareerProfile>;
  listOrders(): Promise<WorkOrder[]>;
  listJobs(profileId: string): Promise<CareerJob[]>;
  acceptOrder(profileId: string, orderId: string): Promise<CareerJob>;
  settleJob(jobId: string): Promise<CareerJob>;
}

export const careerApi: CareerApi = {
  async getProfile(profileId) {
    return GetProfileApiV1CareerProfilesProfileIdGetResponse.parse(await getProfileApiV1CareerProfilesProfileIdGet(profileId));
  },
  async listOrders() {
    return ListOrdersApiV1CareerOrdersGetResponse.parse(await listOrdersApiV1CareerOrdersGet());
  },
  async listJobs(profileId) {
    return ListJobsApiV1CareerProfilesProfileIdJobsGetResponse.parse(await listJobsApiV1CareerProfilesProfileIdJobsGet(profileId));
  },
  async acceptOrder(profileId, orderId) {
    const job = await acceptOrderApiV1CareerProfilesProfileIdJobsPost(profileId, { order_id: orderId });
    return AcceptOrderApiV1CareerProfilesProfileIdJobsPostResponse.parse(job);
  },
  async settleJob(jobId) {
    return SettleJobApiV1CareerJobsJobIdSettlePostResponse.parse(await settleJobApiV1CareerJobsJobIdSettlePost(jobId));
  },
};
